"""
BATAGOTA 조직형 실행 계층
- 관리자(Manager) -> 과장(Section Manager) -> 대리(Deputy Executor)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict


@dataclass
class DeputyExecutor:
    role_name: str

    def execute(self, handler_name: str, intent: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if handler_name == "mqtt_handler":
            from core.agent.mqtt_handler import mqtt_router

            return mqtt_router(intent, params)

        if handler_name == "generic_data_handler":
            from core.agent.generic_data_handler import generic_router

            return generic_router(intent, params)

        if handler_name == "stock_handler":
            from core.agent.stock_handler import stock_router

            return stock_router(intent, params)

        if handler_name == "app_server_handler":
            from core.agent.app_server_handler import app_server_router

            return app_server_router(intent, params)

        if handler_name == "project_handler":
            return {
                "status": "not_implemented",
                "intent": intent,
                "error": "project_handler is not implemented yet",
            }

        return {
            "status": "error",
            "intent": intent,
            "error": f"Unknown handler: {handler_name}",
        }


@dataclass
class SectionManager:
    role_name: str
    deputy: DeputyExecutor

    def run(self, handler_name: str, intent: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.deputy.execute(handler_name=handler_name, intent=intent, params=params)


class ManagerAgent:
    """요청을 분배하고 실행 결과를 조직 추적 정보와 함께 반환한다."""

    def __init__(self, routing_table: Dict[str, Dict[str, Any]]):
        self.routing_table = routing_table
        self.section_managers = {
            "mqtt_handler": SectionManager("mqtt_section_manager", DeputyExecutor("mqtt_deputy_executor")),
            "generic_data_handler": SectionManager(
                "data_section_manager", DeputyExecutor("data_deputy_executor")
            ),
            "stock_handler": SectionManager("stock_section_manager", DeputyExecutor("stock_deputy_executor")),
            "app_server_handler": SectionManager(
                "app_server_section_manager", DeputyExecutor("app_server_deputy_executor")
            ),
            "project_handler": SectionManager(
                "project_section_manager", DeputyExecutor("project_deputy_executor")
            ),
        }

    def execute_task(self, intent: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if intent not in self.routing_table:
            return {
                "status": "error",
                "intent": intent,
                "error": f"Unknown intent: {intent}",
                "org_trace": {
                    "manager": "manager_agent",
                    "section_manager": None,
                    "deputy": None,
                },
            }

        route = self.routing_table[intent]
        handler_name = route.get("handler")
        section_manager = self.section_managers.get(handler_name)

        if section_manager is None:
            return {
                "status": "error",
                "intent": intent,
                "error": f"No section manager mapped for handler: {handler_name}",
                "org_trace": {
                    "manager": "manager_agent",
                    "section_manager": None,
                    "deputy": None,
                },
            }

        result = section_manager.run(handler_name=handler_name, intent=intent, params=params)

        payload: Dict[str, Any] = {
            "status": result.get("status", "error"),
            "intent": intent,
            "result": result,
            "org_trace": {
                "manager": "manager_agent",
                "section_manager": section_manager.role_name,
                "deputy": section_manager.deputy.role_name,
                "handler": handler_name,
                "project": route.get("project"),
                "priority": route.get("priority"),
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        if result.get("output_file"):
            payload["output_file"] = result.get("output_file")
        if result.get("output_type"):
            payload["output_type"] = result.get("output_type")
        if result.get("error"):
            payload["error"] = result.get("error")

        return payload
