# Security Model

The `db-graphql-gateway` embraces a **"defense in depth"** security architecture. It protects against structural leaks, data access violations, and malicious denial-of-service query structures.

## 1. Authentication (JWT)

The Gateway ships with a pluggable `AuthenticationProvider`. By default, it supports symmetric (`HS256`) and asymmetric (`RS256`) PyJWT validation.

> [!WARNING]
> Always verify that your PyJWT implementation strictly specifies the `algorithms` array during decoding to prevent **Algorithm Confusion Attacks** (e.g., passing an RSA public key as an HMAC secret). The Gateway's internal provider mitigates this by enforcing strict algorithm pairing.

The provider:
1. Extracts `Authorization: Bearer <token>` from HTTP headers.
2. Validates the signature, expiration, issuer, and audience.
3. Injects a verified `AuthContext` into the GraphQL resolving pipeline.

## 2. Row-Level Authorization

Unlike application-layer filtering—which is prone to memory leaks and authorization bypasses—the Gateway's `AuthorizationEngine` transpiles security policies directly into SQL `WHERE` clauses.

For example, a policy defining `$user_id = owner_id` on the `tasks` table will statically inject `AND owner_id = $1` into the generated SQL query for both top-level lists and nested relations. 

**This ensures that a user can *never* query or mutate rows they don't own, because unauthorized rows never leave the database engine.**

## 3. Sensitive Field Redaction

The database schema introspection phase is highly aggressive in discovering tables and columns. However, exposing sensitive data to the graph is a critical risk.

The `GatewayConfig` includes `sensitive_field_patterns` (defaults to `["password", "pwd", "secret", "token", "hash"]`). During the Intermediate Representation (IR) build phase, the Builder automatically redacts any column matching these patterns. They will simply not exist in the final GraphQL Schema unless you explicitly override them via configuration.

## 4. AST DoS Protection (Complexity Budgets)

GraphQL's deeply nested architecture is notoriously vulnerable to Denial of Service (DoS) via exponentially recursive or highly aliased queries.

The Gateway mitigates this via Strawberry **AST Validation Rules** executed before the query ever hits the resolver logic:

- **Max Depth Rule**: Rejects queries exceeding a configured depth limit.
- **Max Aliases Rule**: Prevents expansive execution fan-out attacks by capping the number of aliases allowed in a single request.
- **Max Complexity Rule**: Computes a total point budget for the query based on field selection and nesting, rejecting queries that exceed the budget.

## 5. Production Masking

### Error Masking
In `debug=False` mode, the Gateway intercepts all internal `GraphQLError` exceptions. If an error stems from an underlying `asyncpg` failure, SQL syntax failure, or internal connection issue, the message is standardized to a generic `"Internal server error"`. 

> [!TIP]
> Error masking guarantees that your internal database schema structures, table names, or tracebacks never leak to public clients, even if a bad query causes a SQL exception.

### Introspection Lockdown
By default, GraphQL allows anyone to query `__schema` to download your entire API structure. In production, this can give attackers a perfect map of your database. The Gateway provides an **Introspection Lockdown Rule** to strictly disable introspection queries in production environments.
