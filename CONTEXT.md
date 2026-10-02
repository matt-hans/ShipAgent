# ShipAgent

ShipAgent coordinates provider-led shipping workflows while deterministic
execution remains under ShipAgent control.

## Language

**Approval Request**:
An opaque, short-lived request asking a person to approve or reject one
immutable priced preview on a ShipAgent-owned surface.
_Avoid_: Handoff token, confirmation link

**Approval Surface**:
The ShipAgent-owned boundary that presents an Approval Request and records the
person's explicit approve or reject gesture.
_Avoid_: Confirmation widget, execution page

**Execution Grant**:
A server-side, one-time authorization record proving that a specific immutable
preview was explicitly approved for execution within its stated limits.
_Avoid_: Execution token, confirmation token, approval token

**Exact Approved Purchase**:
The rule that provider-originated execution must match the immutable preview's
shipment inputs, selected rates, currency, and amount without tolerance.
_Avoid_: Cost ceiling when drift is not permitted

**Shipment Source**:
The closed description of where a prepared shipment set comes from: provider
one-off input, a deterministic active-source selection, or an existing batch.
_Avoid_: Order batch when referring to all source variants

**Provisional Selection**:
A deterministic Tier-B filter expansion applied only to build a non-mutating
provider preview before the person approves both its meaning and purchase.
_Avoid_: Confirmed filter, executable selection

**Needs Review**:
A terminal row or job state where a shipment may exist or execution integrity
is uncertain, requiring human reconciliation before any retry.
_Avoid_: Failed when carrier side effects are ambiguous

**Label Download Reference**:
An opaque, short-lived reference that permits one authenticated Cloud Account
to download label artifacts without making label bytes provider-visible.
_Avoid_: Public label URL, signed URL

**Job Reference**:
An opaque provider-visible reference for one execution job, used to poll status
and request its label artifact without exposing the target's local job ID.
_Avoid_: Job ID, poll token

**Provider Connection**:
An independently revocable authorization relationship between one Cloud Account
and one provider client surface.
_Avoid_: Cloud Account, provider session

**Workflow Handoff**:
A transfer of workflow ownership or execution responsibility from the provider
conversation to another client.
_Avoid_: Using this term for an Approval Request

**Execution Target**:
The runtime authorized to perform deterministic shipping work for a Cloud
Account.
_Avoid_: Desktop when the concept also includes future hosted workers
