from graphql import GraphQLError, GraphQLFormattedError


def mask_error_in_production(error: GraphQLError, debug: bool = False) -> GraphQLFormattedError:
    if debug:
        return error.formatted

    # In production, mask internal server errors or SQL syntax/connection errors
    message = str(error.message)
    if "asyncpg" in message.lower() or "sql" in message.lower() or "syntax" in message.lower():
        formatted = error.formatted
        formatted["message"] = "Internal server error"
        return formatted

    return error.formatted
