import importlib
import pkgutil


def register_handlers(app):
    for finder, name, ispkg in pkgutil.iter_modules(__path__):
        if ispkg:
            continue
        module_name = f"{__name__}.{name}"
        module = importlib.import_module(module_name)
        handler_register = getattr(module, "register", None)
        if handler_register:
            handler_register(app)
