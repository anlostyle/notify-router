from fastapi import APIRouter, Depends


def build_task_router(store, admin_auth):
    router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_auth)])

    @router.get("/tasks")
    def tasks():
        items = store.list_tasks()
        return {
            "items": items,
            "summary": {
                "total": len(items),
                "enabled": sum(bool(item["enabled"]) for item in items),
                "failed": sum(item["last_status"] == "failed" for item in items),
                "running": sum(item["last_status"] == "running" for item in items),
            },
            "runs": store.list_task_runs(100),
        }

    @router.get("/events")
    def events(domain: str | None = None, limit: int = 100):
        return store.list_events(domain, max(1, min(limit, 500)))

    return router
