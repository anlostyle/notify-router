from fastapi.responses import JSONResponse


def json_with_status(status_code=200, message="success", data=None):
    return JSONResponse(
        status_code=status_code,
        content={"code": status_code, "message": message, "data": data},
    )


def data_to_json(data=None, message="success"):
    return JSONResponse(content={"code": 200, "message": message, "data": data})


def json_500(message="server error"):
    return json_with_status(500, message=message)
