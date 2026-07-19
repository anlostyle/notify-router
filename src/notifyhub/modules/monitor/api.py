from fastapi import APIRouter, Depends


def build_monitor_router(store, admin_auth):
    router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_auth)])

    @router.get("/monitors")
    def monitors():
        stored = store.list_monitors()
        items = [{key: value for key, value in item.items() if key != "metadata"} for item in stored]
        return {
            "items": items,
            "summary": {
                "total": len(items),
                "healthy": sum(item["status"] in {"up", "healthy", "ok"} for item in items),
                "attention": sum(item["status"] in {"down", "error", "warning"} for item in items),
            },
            "events": store.list_events("monitor", 100),
        }

    return router
