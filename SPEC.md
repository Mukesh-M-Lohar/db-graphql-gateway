# SPEC: Engine-Agnostic GraphQL Generators

## 1. Context & Motivation
Currently, `db-graphql-gateway` is tightly coupled to Strawberry for its GraphQL execution engine. While Strawberry is excellent, tight coupling limits the gateway's adoption for developers using other engines (Ariadne, Graphene, or native Node/Go gateways requiring a raw `.graphql` schema). 
By decoupling the `GraphQLSchemaBuilder` into an engine-agnostic "Generator" pattern, the core gateway logic (Database Adapter -> IR Builder) can remain pristine, while plugins handle the final schema rendering.

## 2. Core Objectives
- Refactor the current `GraphQLSchemaBuilder` out of the core pipeline.
- Define a base `SchemaGenerator` interface.
- Implement the existing Strawberry functionality as `StrawberryGenerator`.
- Implement a `RawSchemaGenerator` to output a standard `.graphql` string.
- Provide a clean API for users to inject custom generators.

## 3. Architecture Changes

### A. Define the Generator Interface
Create `db_graphql_gateway/generators/base.py`:
```python
from abc import ABC, abstractmethod

class SchemaGenerator(ABC):
    def __init__(self, db_adapter):
        self.db_adapter = db_adapter

    @abstractmethod
    def build(self, ir_types, db_schema):
        pass
```

### B. Refactor Strawberry Builder
Move `db_graphql_gateway.graphql.builder` -> `db_graphql_gateway.generators.strawberry.generator.py`.
Rename `GraphQLSchemaBuilder` to `StrawberryGenerator`.

### C. Implement Raw Schema Generator (New Feature)
Create `db_graphql_gateway/generators/raw/generator.py`:
Implement `RawSchemaGenerator` which iterates over the `IR` models and returns a string in standard GraphQL SDL (Schema Definition Language).

### D. Update Gateway Configuration
Modify `create_gateway_app` in `examples/core.py` (and the core usage patterns) to explicitly accept a generator instance:
```python
generator = StrawberryGenerator(db_adapter=adapter)
schema = generator.build(ir_types=ir, db_schema=db_schema)
```

## 4. Test Plan (Empirical Verification)
1. **Strawberry Regression Tests**: Ensure all existing tests pass with the refactored `StrawberryGenerator`.
2. **Raw Schema Test**: Create an integration test that instantiates `RawSchemaGenerator`, passes in the IR, and validates the output against a known GraphQL SDL string.
3. **Example Updates**: Ensure examples reflect the new explicit Generator injection.

## 5. Security & Edge Cases
- No impact on authorization predicates (these operate at the database/IR level).
- Must ensure custom generators have access to the `db_adapter` for resolving queries (for engines that execute, not just generate strings).

## 6. Research: Security Flaws & Industry Best Practices
When exposing a database directly via GraphQL (regardless of the engine), several known pitfalls must be addressed:
1. **Broken Authorization (BOLA/IDOR) on Nested Fields**: The biggest risk. Attackers traverse nested relationships to access records they shouldn't. *Our Mitigation:* We push authorization down to the SQL predicate layer, meaning data is filtered at the DB engine before GraphQL even sees it.
2. **Denial of Service (DoS) via Complexity**: Deeply nested queries or missing pagination can cause CPU spikes or massive DB joins. *Best Practice:* Generators should support (or rely on the engine for) **Query Depth Limiting** and **Query Cost Analysis**. Our single-query guarantee prevents N+1, but deeply nested joins are still expensive.
3. **Schema Exposure & Information Disclosure**: Auto-generated schemas expose internal DB structures. *Best Practice:* Disable introspection in production or use **Persisted Queries / Allowlisting** so only known frontend queries are allowed.
4. **Injection Attacks**: Passing GraphQL arguments directly to SQL. *Our Mitigation:* All arguments are strictly parameterized via `asyncpg`/`aiosqlite`.

## 7. Observability & OpenTelemetry (Upcoming)
To make this gateway truly enterprise-ready, we must support **OpenTelemetry (OTel)** out of the box. 
When a request hits the gateway, developers should see a distributed trace that covers:
1. **GraphQL Parsing:** The time taken by the specific engine to parse the query.
2. **IR Compilation:** The time taken to convert the GraphQL AST into our Intermediate Representation (IR).
3. **SQL Generation:** The time spent compiling the IR into parameterized SQL.
4. **Database Execution:** The exact SQL execution time and database response.

*Action Item:* The `SchemaGenerator` interface and `db_adapter` must accept tracer contexts so we can propagate span IDs from the GraphQL layer down to the SQL driver.

## 8. Implementation Steps (Current Sprint)
- [x] Create `feature/engine-agnostic` branch.
- [ ] Define `SchemaGenerator` base class.
- [ ] Move and rename `StrawberryGenerator`.
- [ ] Fix internal imports and test references.
- [ ] Develop `RawSchemaGenerator`.
- [ ] Draft OpenTelemetry Integration specification.
- [ ] Update documentation and examples to showcase engine agnosticism.

## 9. Future Enterprise Roadmap (Post-Agnostic Core)
Once the core is engine-agnostic, the following enterprise features will be prioritized:
1. **Real-time Subscriptions (WebSockets):** Utilizing PostgreSQL `LISTEN/NOTIFY` and logical replication to stream live database updates back to GraphQL subscriptions.
2. **Custom Actions / Webhooks:** Providing an API for developers to register custom Python functions or external webhooks for complex mutations and business logic, bypassing the auto-generated SQL.
3. **Edge Caching & Redis Integration:** AST-based query hashing to check Redis caches before compiling IR to SQL, dramatically reducing database load for frequent queries.
