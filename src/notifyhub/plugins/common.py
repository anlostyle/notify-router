import inspect


_after_setup_hooks = []


def after_setup(plugin_id, desc=""):
    def decorator(func):
        _after_setup_hooks.append((plugin_id, desc, func))
        return func

    return decorator


async def run_after_setup_hooks(logger):
    for plugin_id, desc, func in _after_setup_hooks:
        try:
            result = func()
            if inspect.isawaitable(result):
                await result
            logger.info("plugin initialized: %s %s", plugin_id, desc)
        except Exception:
            logger.exception("plugin initialization failed: %s %s", plugin_id, desc)
