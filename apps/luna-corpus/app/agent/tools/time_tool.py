"""Time tool for getting current date and time."""
from datetime import datetime
from app.agent.tool import tool


current_time_tool = tool(
    name="current_time",
    description="Get the current date and time. Useful for time-related questions.",
    parameters_schema={
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": (
                    "Time format string (default: '%Y-%m-%d %H:%M:%S')"
                ),
                "default": "%Y-%m-%d %H:%M:%S",
            },
        },
    },
)(lambda format="%Y-%m-%d %H:%M:%S": datetime.now().strftime(format))
