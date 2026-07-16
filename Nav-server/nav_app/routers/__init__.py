"""FastAPI routers for nav server HTTP surface."""
from nav_app.routers import locks, meta, mission, movement_api, robot_commands, scenario_api

ROUTERS = (
    meta.router,
    movement_api.router,
    scenario_api.router,
    robot_commands.router,
    locks.router,
    mission.router,
)


def include_routers(app):
    for router in ROUTERS:
        app.include_router(router)
