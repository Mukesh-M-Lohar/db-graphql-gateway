import yaml
from fastapi import FastAPI
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.integrations.fastapi_integration import make_graphql_router

def create_gateway_app(adapter, config_path=None):
    """
    Creates a FastAPI app with a mounted GraphQL router for the given database adapter.
    """
    app = FastAPI(title="GraphQL Gateway Example")
    
    config_data = {}
    if config_path:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)
    config = GatewayConfig(**config_data)

    @app.on_event("startup")
    async def startup():
        await adapter.connect()
        inspector = adapter.inspector()
        db_schema = await inspector.discover_schema()
        
        ir_builder = IRBuilder(type_mapper=adapter.type_mapper())
        ir = ir_builder.build(db_schema=db_schema, config=config)
        
        schema_builder = GraphQLSchemaBuilder(db_adapter=adapter)
        schema = schema_builder.build(ir_types=ir, db_schema=db_schema)
        
        graphql_router = make_graphql_router(schema)
        app.include_router(graphql_router, prefix="/graphql")
        
    @app.on_event("shutdown")
    async def shutdown():
        await adapter.close()
        
    return app
