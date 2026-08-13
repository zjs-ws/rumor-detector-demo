import os

from pydantic import BaseModel, Field


class GatewayConfig(BaseModel):
    """Configuration for the API Gateway."""

    host: str = Field(default="0.0.0.0", description="Host to bind the gateway server")
    port: int = Field(default=8001, description="Port to bind the gateway server")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"], description="Allowed CORS origins")
    langgraph_url: str = Field(
        default="http://localhost:2024",
        description="Internal LangGraph Server URL",
    )
    rumor_agent_graph_id: str = Field(
        default="rumor_agent",
        description="LangGraph graph ID used by the fact-check API",
    )
    rumor_check_timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        description="Maximum synchronous fact-check wait time",
    )


_gateway_config: GatewayConfig | None = None


def get_gateway_config() -> GatewayConfig:
    """Get gateway config, loading from environment if available."""
    global _gateway_config
    if _gateway_config is None:
        cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        _gateway_config = GatewayConfig(
            host=os.getenv("GATEWAY_HOST", "0.0.0.0"),
            port=int(os.getenv("GATEWAY_PORT", "8001")),
            cors_origins=cors_origins_str.split(","),
            langgraph_url=os.getenv("LANGGRAPH_INTERNAL_URL", "http://localhost:2024"),
            rumor_agent_graph_id=os.getenv("RUMOR_AGENT_GRAPH_ID", "rumor_agent"),
            rumor_check_timeout_seconds=float(os.getenv("RUMOR_CHECK_TIMEOUT_SECONDS", "120")),
        )
    return _gateway_config
