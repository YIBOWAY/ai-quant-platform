# AI Quant Research and Paper Trading Context

This context defines the project-specific language for the local AI quant research and paper-trading platform. It is a glossary, not an implementation plan.

## Language

**Persistent Paper Account**:
The single local paper account that aggregates manual paper activity and strategy-sleeve paper activity for combined review.
_Avoid_: Strategy account, separate paper account

**Manual Sleeve**:
The default ownership segment for user-directed paper cash and paper lots inside the persistent paper account.
_Avoid_: Unallocated bucket, default strategy

**Strategy Sleeve**:
A strategy-owned segment inside the persistent paper account with its own cash, lots, lifecycle, and performance attribution.
_Avoid_: Strategy account, rebalance account

**Sleeve Lot**:
A paper holding lot owned by exactly one manual or strategy sleeve; ordinary manual sells do not consume strategy-sleeve lots.
_Avoid_: Shared position, blended holding

**Lot Transfer**:
An explicit ownership change that moves an existing sleeve lot from one sleeve to another; it is outside Paper Strategy Sleeves MVP-1.
_Avoid_: Implicit adoption, inherited holding

**Allocated Sleeve Cash**:
Cash explicitly moved from the manual sleeve into a strategy sleeve; manual orders cannot spend it unless the user first transfers it back.
_Avoid_: Virtual principal, shared account cash

**Signal-Only Sleeve**:
A strategy sleeve that observes and records strategy signals without owning cash or changing paper-account holdings.
_Avoid_: Paper trading strategy, dormant allocation

**Paused Sleeve**:
A strategy sleeve whose execution is blocked while its strategy may still record observation signals.
_Avoid_: Stopped sleeve, archived strategy

**Manual Intervention**:
An explicit user action that changes a strategy sleeve's cash, lots, or lifecycle outside that sleeve's own strategy logic.
_Avoid_: Normal manual order, automatic rebalance

**Remediation Package**:
A bounded bundle of assessment-driven project improvement work with a defined scope, acceptance evidence, and stop condition.
_Avoid_: Phase, open-ended project optimization

**Remediation Goal**:
A long-running agent objective that advances one remediation package at a time and stops only when the package queue is complete or a user decision is required.
_Avoid_: Optimize everything, continuous cleanup
