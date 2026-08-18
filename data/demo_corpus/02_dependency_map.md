# Helios Platform - Runtime Dependency Map

This document records the runtime call graph between production services. It is generated from distributed tracing data and reviewed by the architecture group each month.

The checkout-api depends on payments-gateway for authorisation of every order. A failure in that path surfaces to the customer as a declined checkout, so it is treated as a tier-one dependency.

The checkout-api depends on identity-broker for session validation on every inbound request.

The payments-gateway depends on ledger-service for write-ahead recording of every authorisation attempt before the card network is contacted.

The payments-gateway depends on fraud-scorer for the inline risk decision that gates authorisation.

The ledger-service depends on postgres-primary for durable storage. The ledger-service runs on the shared transactional cluster rather than dedicated hardware.

The fraud-scorer depends on feature-store for the behavioural signals used in scoring.

The notification-relay depends on ledger-service for settlement confirmation events.

Dependency direction matters when reasoning about blast radius. An outage in ledger-service degrades payments-gateway, which in turn degrades checkout-api, even though checkout-api never calls ledger-service directly. This transitive path is the most common source of misrouted incident tickets on the platform.
