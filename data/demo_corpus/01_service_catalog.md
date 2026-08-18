# Helios Platform - Service Catalog

The Helios platform is organised into fourteen production services. This catalog records ownership for each service so that incident responders can find an accountable team without paging the whole organisation.

The checkout-api is owned by Team Aurora. It handles cart finalisation, tax calculation and order submission for all storefronts. Team Aurora also owns the cart-session store used during checkout.

The payments-gateway is owned by Team Meridian. It brokers all outbound authorisation traffic to card networks and is the only service permitted to hold tokenised instrument references.

The ledger-service is owned by Team Borealis. It is the system of record for settled transactions and produces the daily reconciliation extract consumed by Finance.

The fraud-scorer is owned by Team Meridian. It evaluates risk signals inline during authorisation and returns a decision within a strict latency budget.

The notification-relay is owned by Team Cascade. It fans out transactional email and push messages triggered by order lifecycle events.

The identity-broker is owned by Team Vega. It issues and validates the short-lived tokens that every other service uses for authentication.

Ownership is reviewed quarterly. A service without a recorded owner cannot be promoted to production; this rule is enforced by the deployment pipeline at the release gate.
