import asyncio
from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.schema.ir.builder import IRBuilder
from db_graphql_gateway.schema.config import GatewayConfig
from tests.conformance.conftest import get_ddl


def test_benchmark_sqlite_query(benchmark):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Setup minimal DB
    adapter = SQLiteAdapter(":memory:")
    loop.run_until_complete(adapter.connect())
    conn = adapter._conn
    for stmt in get_ddl("sqlite"):
        loop.run_until_complete(conn.execute(stmt))

    loop.run_until_complete(
        conn.execute("INSERT INTO authors (id, name) VALUES (1, 'Tolkien'), (2, 'Asimov')")
    )
    loop.run_until_complete(
        conn.execute(
            "INSERT INTO books (title, author_id) VALUES ('The Hobbit', 1), ('Foundation', 2), ('LOTR', 1)"
        )
    )
    loop.run_until_complete(conn.commit())

    inspector = adapter.inspector()
    db_schema = loop.run_until_complete(inspector.discover_schema())
    ir_builder = IRBuilder(type_mapper=adapter.type_mapper())
    ir_types = ir_builder.build(db_schema, GatewayConfig())
    schema = GraphQLSchemaBuilder(adapter).build(ir_types, db_schema)

    query = """
    query {
        authors {
            id
            name
            books {
                title
            }
        }
    }
    """

    def run_query_sync():
        res = loop.run_until_complete(schema.execute(query, context_value={}))
        assert res.errors is None
        return res

    benchmark(run_query_sync)
    loop.run_until_complete(adapter.close())
    loop.close()
