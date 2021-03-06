import logging
from enum import Enum

from fastapi import FastAPI, HTTPException

from ..manager.comms import ZMQCommSendAsync
from .conversions import filter_plan_descriptions

logger = logging.getLogger(__name__)


# Login and authentication are not implemented, but some API methods require
#   login data. So for now we set up fixed user name and group
_login_data = {"user": "John Doe", "user_group": "admin"}

logging.basicConfig(level=logging.WARNING)
logging.getLogger("bluesky_queueserver").setLevel("DEBUG")

# Use FastAPI
app = FastAPI()
zmq_to_manager = None


@app.on_event("startup")
async def startup_event():
    global zmq_to_manager
    # ZMQCommSendAsync should be created from the event loop of FastAPI server.
    zmq_to_manager = ZMQCommSendAsync(raise_exceptions=False)


@app.on_event("shutdown")
def shutdown_event():
    global zmq_to_manager
    zmq_to_manager.close()


class REPauseOptions(str, Enum):
    deferred = "deferred"
    immediate = "immediate"


def validate_payload_keys(payload, *, required_keys=None, optional_keys=None):
    """
    Validate keys in the payload. Raise an exception if the request contains unsupported
    keys or if some of the required keys are missing.

    Parameters
    ----------
    payload: dict
        Payload received with the request.
    required_keys: list(str)
        List of the required payload keys. All the keys must be present in the request.
    optional_keys: list(str)
        List of optional keys.

    Raises
    ------
    ValueError
        payload contains unsupported keys or some of the required keys are missing.
    """

    # TODO: it would be better to use something similar to 'jsonschema' validator.
    #   Unfortunately 'jsonschema' provides terrible error reporting.
    #   Any suggestions?
    #   For now let's use primitive validaator that ensures that the dictionary
    #   has necessary and only allowed top level keys.

    required_keys = required_keys or []
    optional_keys = optional_keys or []

    payload_keys = list(payload.keys())
    r_keys = set(required_keys)
    a_keys = set(required_keys).union(set(optional_keys))
    extra_keys = set()

    for key in payload_keys:
        if key not in a_keys:
            extra_keys.add(key)
        else:
            r_keys -= {key}

    err_msg = ""
    if r_keys:
        err_msg += f"Some required keys are missing in the request: {r_keys}. "
    if extra_keys:
        err_msg += f"Request contains keys the are not supported: {extra_keys}."

    if err_msg:
        raise ValueError(err_msg)


@app.get("/")
@app.get("/ping")
async def ping_handler():
    """
    May be called to get some response from the server. Currently returns status of RE Manager.
    """
    msg = await zmq_to_manager.send_message(method="ping")
    return msg


@app.get("/status")
async def status_handler():
    """
    Returns status of RE Manager.
    """
    msg = await zmq_to_manager.send_message(method="status")
    return msg


@app.get("/queue/get")
async def queue_get_handler():
    """
    Returns the contents of the current queue.
    """
    msg = await zmq_to_manager.send_message(method="queue_get")
    return msg


@app.post("/queue/clear")
async def queue_clear_handler():
    """
    Clear the plan queue.
    """
    msg = await zmq_to_manager.send_message(method="queue_clear")
    return msg


@app.post("/queue/start")
async def queue_start_handler():
    """
    Start execution of the loaded queue. Additional runs can be added to the queue while
    it is executed. If the queue is empty, then nothing will happen.
    """
    msg = await zmq_to_manager.send_message(method="queue_start")
    return msg


@app.post("/queue/stop")
async def queue_stop():
    """
    Activate the sequence of stopping the queue. The currently running plan will be completed,
    but the next plan will not be started. The request will be rejected if no plans are currently
    running
    """
    msg = await zmq_to_manager.send_message(method="queue_stop")
    return msg


@app.post("/queue/stop/cancel")
async def queue_stop_cancel():
    """
    Cancel pending request to stop the queue while the current plan is still running.
    It may be useful if the `/queue/stop` request was issued by mistake or the operator
    changed his mind. Since `/queue/stop` takes effect only after the currently running
    plan is completed, user may have time to cancel the request and continue execution of
    the queue. The command always succeeds, but it has no effect if no queue stop
    requests are pending.
    """
    msg = await zmq_to_manager.send_message(method="queue_stop_cancel")
    return msg


@app.post("/queue/item/add")
async def queue_item_add_handler(payload: dict):
    """
    Adds new plan to the queue
    """
    # TODO: validate inputs!
    params = payload
    params["user"] = _login_data["user"]
    params["user_group"] = _login_data["user_group"]
    msg = await zmq_to_manager.send_message(method="queue_item_add", params=params)
    return msg


@app.post("/queue/item/remove")
async def qqueue_item_remove_handler(payload: dict):
    """
    Remove plan from the queue
    """
    msg = await zmq_to_manager.send_message(method="queue_item_remove", params=payload)
    return msg


@app.post("/queue/item/move")
async def queue_item_move_handler(payload: dict):
    """
    Remove plan from the queue
    """
    msg = await zmq_to_manager.send_message(method="queue_item_move", params=payload)
    return msg


@app.post("/queue/item/get")
async def queue_item_get_handler(payload: dict):
    """
    Get a plan from the queue
    """
    msg = await zmq_to_manager.send_message(method="queue_item_get", params=payload)
    return msg


@app.get("/history/get")
async def history_get_handler():
    """
    Returns the plan history (list of dicts).
    """
    msg = await zmq_to_manager.send_message(method="history_get")
    return msg


@app.post("/history/clear")
async def history_clear_handler():
    """
    Clear plan history.
    """
    msg = await zmq_to_manager.send_message(method="history_clear")
    return msg


@app.post("/environment/open")
async def environment_open_handler():
    """
    Creates RE environment: creates RE Worker process, starts and configures Run Engine.
    """
    msg = await zmq_to_manager.send_message(method="environment_open")
    return msg


@app.post("/environment/close")
async def environment_close_handler():
    """
    Orderly closes of RE environment. The command returns success only if no plan is running,
    i.e. RE Manager is in the idle state. The command is rejected if a plan is running.
    """
    msg = await zmq_to_manager.send_message(method="environment_close")
    return msg


@app.post("/environment/destroy")
async def environment_destroy_handler():
    """
    Destroys RE environment by killing RE Worker process. This is a last resort command which
    should be made available only to expert level users.
    """
    msg = await zmq_to_manager.send_message(method="environment_destroy")
    return msg


@app.post("/re/pause")
async def re_pause_handler(payload: dict):
    """
    Pause Run Engine.
    """
    try:
        validate_payload_keys(payload, required_keys=["option"])
        if not hasattr(REPauseOptions, payload["option"]):
            raise ValueError(
                f'The specified option "{payload["option"]}" is not allowed.\n'
                f"Allowed options: {list(REPauseOptions.__members__.keys())}"
            )
    except Exception as ex:
        raise HTTPException(status_code=444, detail=str(ex))

    msg = await zmq_to_manager.send_message(method="re_pause", params=payload)
    return msg


@app.post("/re/resume")
async def re_resume_handler():
    """
    Run Engine: resume execution of a paused plan
    """
    msg = await zmq_to_manager.send_message(method="re_resume")
    return msg


@app.post("/re/stop")
async def re_stop_handler():
    """
    Run Engine: stop execution of a paused plan
    """
    msg = await zmq_to_manager.send_message(method="re_stop")
    return msg


@app.post("/re/abort")
async def re_abort_handler():
    """
    Run Engine: abort execution of a paused plan
    """
    msg = await zmq_to_manager.send_message(method="re_abort")
    return msg


@app.post("/re/halt")
async def re_halt_handler():
    """
    Run Engine: halt execution of a paused plan
    """
    msg = await zmq_to_manager.send_message(method="re_halt")
    return msg


@app.get("/re/runs/active")
async def re_runs_active_handler():
    """
    Run Engine: download the list of active runs (runs that were opened during execution of
    the currently running plan and combines the subsets of 'open' and 'closed' runs.)
    """
    params = {"option": "active"}
    msg = await zmq_to_manager.send_message(method="re_runs", params=params)
    return msg


@app.get("/re/runs/open")
async def re_runs_open_handler():
    """
    Run Engine: download the subset of active runs that includes runs that were open, but not yet closed.
    """
    params = {"option": "open"}
    msg = await zmq_to_manager.send_message(method="re_runs", params=params)
    return msg


@app.get("/re/runs/closed")
async def re_runs_closed_handler():
    """
    Run Engine: download the subset of active runs that includes runs that were already closed.
    """
    params = {"option": "closed"}
    msg = await zmq_to_manager.send_message(method="re_runs", params=params)
    return msg


@app.get("/plans/allowed")
async def plans_allowed_handler():
    """
    Returns the lists of allowed plans.
    """
    params = {"user_group": _login_data["user_group"]}
    msg = await zmq_to_manager.send_message(method="plans_allowed", params=params)
    if "plans_allowed" in msg:
        msg["plans_allowed"] = filter_plan_descriptions(msg["plans_allowed"])
    return msg


@app.get("/devices/allowed")
async def devices_allowed_handler():
    """
    Returns the lists of allowed devices.
    """
    params = {"user_group": _login_data["user_group"]}
    msg = await zmq_to_manager.send_message(method="devices_allowed", params=params)
    return msg


@app.post("/permissions/reload")
async def permissions_reload_handler():
    """
    Reloads the list of allowed plans and devices and user group permission from the default location
    or location set using command line parameters of RE Manager. Use this request to reload the data
    if the respective files were changed on disk.
    """
    msg = await zmq_to_manager.send_message(method="permissions_reload")
    return msg


@app.post("/manager/stop")
async def manager_stop_handler(payload: dict):
    """
    Stops of RE Manager. RE Manager will not be restarted after it is stoped.
    """
    msg = await zmq_to_manager.send_message(method="manager_stop", params=payload)
    return msg


@app.post("/test/manager/kill")
async def test_manager_kill_handler():
    """
    The command stops event loop of RE Manager process. Used for testing of RE Manager
    stability and handling of communication timeouts.
    """
    msg = await zmq_to_manager.send_message(method="manager_kill")
    return msg
