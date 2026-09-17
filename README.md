# gpu-term-premium

Measures one number, per GPU SKU, per region, per cloud:

```
term premium  =  spot price  /  three-year committed price
```

What the hourly market charges for a machine, as a multiple of what the seller
accepts to lock that same machine away for three years.

| reading | meaning |
|---|---|
| **> 1.0** | Hourly buyers outbid committed buyers. Normal for scarce silicon. |
| **< 1.0** | The seller rents it today, no commitment, **below** what it charges customers who commit for three years. That is not a discount schedule. That is inventory that will not move. |

AWS, Azure and GCP all publish both legs for free. Nobody puts them in a ratio.

## Why a ratio and not a price

- **Scale-invariant.** Numerator and denominator are the same SKU, so GPU count,
  vCPU, RAM and disk cancel out. No hardware spec table is needed, and none can
  be got wrong. A 1-GPU box and an 8-GPU box give comparable numbers.
- **Cross-cloud comparable.** Comparing an AWS `g7e.2xlarge` to an Azure
  `NC144ds_xl` in dollars requires a normalisation you have to defend. A ratio
  compares each seller to *its own* committed book, so it survives the clouds
  packaging the same chip differently.
- **Discount- and currency-neutral.** Enterprise discounts and FX hit both legs.

## Install and run

```bash
pip install -r requirements.txt

python -m gpu_term_premium collect --clouds aws azure   # ~5 min, writes data/
python -m gpu_term_premium report                       # the table
python -m gpu_term_premium ladder                       # size monotonicity
python -m gpu_term_premium report --csv > premium.csv
```

AWS needs read-only credentials (`ec2:DescribeSpotPriceHistory`,
`pricing:GetProducts`, `savingsplans:DescribeSavingsPlansOfferingRates`). Azure
needs nothing at all — its Retail Prices API is anonymous. GCP needs an API key
in `GCP_BILLING_API_KEY`; without one it is skipped rather than failing the run.

## Where the numbers come from

| cloud | spot leg | commitment leg | auth |
|---|---|---|---|
| AWS | `ec2:describe-spot-price-history`, latest print per AZ | `savingsplans:describe-savings-plans-offering-rates`, EC2 Instance plan, All Upfront | IAM, read-only |
| Azure | Retail Prices API, `Consumption` rows with " Spot" in meterName | Retail Prices API, `Reservation` rows, 3 Years | none |
| GCP | Billing Catalog, `usageType=Preemptible` | Billing Catalog, `usageType=Commit3Yr` | API key |

Everything upstream is archived gzipped under `data/raw/dt=YYYY-MM-DD/` before
any arithmetic. A published figure can always be traced back to the bytes the
vendor served. `data/panel/` holds the tidy rows.

## Four traps that produce plausible wrong numbers

These are pinned in `tests/test_ratio.py` rather than trusted.

1. **AWS g7/g7e have no Reserved Instances at all.**
   `DescribeReservedInstancesOfferings` rejects the instance type outright
   (`InvalidInput: Unrecognizable instance type`) while accepting `g6e` happily.
   An RI-based comparison silently drops exactly the chips under discussion.
   This tool uses **EC2 Instance Savings Plans**, which do cover them. If you
   publish a "three-year price" for a g7, say which instrument it is — a reader
   who checks the RI price finds nothing and concludes you invented it.

2. **Azure reservation rows are a whole-term lump sum labelled "1 Hour".**
   `retailPrice: 127195.0` with `unitOfMeasure: "1 Hour"` is $127,195 for three
   years, i.e. $4.84/hr. Taken at face value it overstates the commitment leg by
   four orders of magnitude and makes every SKU look wildly inverted.

3. **Azure `DevTestConsumption` rows are not market prices.** They are a
   subscription-gated discount, roughly half the real rate, and they sit in the
   same response as the genuine ones.

4. **Spot must be averaged over pools, not over events.** Each AZ is a separate
   capacity pool that reprices on its own schedule. Averaging raw price-change
   events lets a volatile AZ dominate the regional figure. This tool reduces to
   the latest print per AZ first.

## Limits, stated because the number invites overreach

- **AWS spot is not an auction.** It has been an administered, smoothed price
  since November 2017. This is a seller's posted price, not an order book.
- **GCP spot is administered outright**, reset on roughly a monthly cadence by
  decision. Its *level* carries little capacity information; only its *changes*
  do. Do not apply the AWS reading to GCP — see `collectors/gcp.py`.
- **A quoted price is not available capacity.** A spot price is published for
  SKUs that cannot actually be launched. A low ratio on a frontier chip may mean
  a phantom market rather than a soft one. Corroborate with an actual launch
  before drawing conclusions about scarce parts.
- **The commitment leg is a list price.** Large buyers negotiate below it, which
  biases the ratio *upward* — so a reading below 1.0 is conservative.
- **A single inverted pair is weak.** One SKU in one region can invert from pool
  fragmentation: a machine shape nobody happens to want, which is a much more
  local claim than an idle fleet. Use `ladder` to check whether a whole family
  inverts, and check other regions, before generalising.
- **Only AWS gives history.** `describe-spot-price-history` returns 90 days for
  free. Azure's Retail Prices API and GCP's catalog serve *current* prices only,
  with no history and no archive anywhere upstream. The Azure and GCP series
  therefore begin the day you first run `collect` and accrue forward — which is
  the reason the raw layer exists. Run it daily from now, or there is nothing to
  compare next month against.

## A cross-cloud check the ratio makes possible

The same physical card carries opposite signals on different clouds:

| chip | AWS median | Azure median |
|---|---|---|
| RTX PRO 6000 (96 GB) | **1.79** | **0.65** |
| H100 (80 GB) | 1.00 | 0.43 |
| H200 (141 GB) | 1.14 | **2.06** |

Measured 2026-09-17, three US regions each. The H200 row is what makes this
worth reporting: if Azure simply priced all its commitments high, every Azure
ratio would sit low. One chip running the other way means the divergence is
per-chip, so it is about that chip's inventory on that cloud — not a pricing
convention. Any claim that a given card is "scarce" needs naming which cloud it
is scarce *on*.

## `ladder`

Within a family, price normally rises with size — more vCPU and RAM around the
same GPU costs more. `ladder` prints each rung and flags non-monotonic families:

```
aws   us-west-2   g7   2xl=0.777  4xl=0.701  8xl=1.038   <-- INVERTED
```

An inversion at one rung is a fragmented pool. An inversion across every rung of
a family, in several regions, is something larger. The command exists so the
difference is visible instead of being asserted.
