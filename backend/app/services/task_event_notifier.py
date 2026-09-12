"""提交后的任务事件通知：Redis Pub/Sub 只做"某任务有新事件"的唤醒。

通知不是任务结果，不代表浏览器已收到，也不是重新调用模型的依据。
通知丢失可容忍：SSE 消费者按游标从 MySQL 补读。发布失败只记录降级。

每个 API 进程一条订阅长连接；唤醒标记按 task_id 可合并，不为每个
浏览器建立 Redis 连接或无限内存队列。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterable

import structlog
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.redis_client import RedisUnavailable, execute
from app.models.task_event import TaskSignal

logger = structlog.get_logger()

_PUBLISH_BUDGET_SECONDS = 0.2  # 一次批量通知总等待不超过 200 ms
_LISTENER_TICK_SECONDS = 5.0
_RECONNECT_DELAY_SECONDS = 1.5

_wake_events: dict[str, set[asyncio.Event]] = {}
_listener_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def channel() -> str:
    return f"{get_settings().redis_key_prefix}:notify:tasks"


def merge_signals(signals: Iterable[TaskSignal]) -> list[TaskSignal]:
    """同任务只保留最大 seq。"""
    merged: dict[str, TaskSignal] = {}
    for signal in signals:
        current = merged.get(signal.task_id)
        if current is None or signal.seq > current.seq:
            merged[signal.task_id] = signal
    return list(merged.values())


async def publish_signals(signals: Iterable[TaskSignal]) -> None:
    signals = list(signals)
    settings = get_settings()
    if not settings.redis_enabled or not signals:
        return
    payload = json.dumps(
        [signal.model_dump(mode="json") for signal in merge_signals(signals)],
        separators=(",", ":"),
    )

    async def op(client):
        return await client.publish(channel(), payload)

    try:
        await asyncio.wait_for(execute(op), timeout=_PUBLISH_BUDGET_SECONDS)
    except (RedisUnavailable, asyncio.TimeoutError) as exc:
        logger.warning(
            "task_event_publish_degraded", reason=type(exc).__name__, count=len(signals)
        )


def wake_handle(task_id: str) -> asyncio.Event:
    """登记本进程内某个活动任务订阅的唤醒标记；同任务多订阅共享一个标记。"""
    event = asyncio.Event()
    _wake_events.setdefault(task_id, set()).add(event)
    return event


def release_wake(task_id: str, event: asyncio.Event) -> None:
    waiters = _wake_events.get(task_id)
    if waiters is not None:
        waiters.discard(event)
        if not waiters:
            _wake_events.pop(task_id, None)


async def wait_for_wake(task_id: str, timeout_seconds: float) -> bool:
    """等待唤醒或超时；返回是否因通知唤醒。定时补读由调用方的 timeout 兜底。"""
    event = wake_handle(task_id)
    try:
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
            return True
        except asyncio.TimeoutError:
            return False
    finally:
        release_wake(task_id, event)


def _dispatch_wake(task_ids) -> int:
    woken = 0
    for task_id in task_ids:
        for event in _wake_events.get(task_id, ()):  # 合并：同一任务只置一次
            event.set()
            woken += 1
    return woken


def new_listener_client() -> Redis:
    """Pub/Sub 使用独立长连接，不套用普通命令的 100ms 读超时。"""
    settings = get_settings()
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password,
        ssl=settings.redis_tls,
        socket_connect_timeout=2.0,
        # 阻塞读取由 get_message(timeout) 控制；socket 不设短超时。
        socket_timeout=None,
        health_check_interval=30,
    )


async def _listen_loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    while not stop.is_set():
        client = None
        pubsub = None
        try:
            client = new_listener_client()
            pubsub = client.pubsub()
            await pubsub.subscribe(channel())
            logger.info("task_event_listener_started")
            while not stop.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=_LISTENER_TICK_SECONDS
                )
                if message and message.get("data"):
                    try:
                        signals = [
                            TaskSignal.model_validate(item)
                            for item in json.loads(message["data"])
                        ]
                    except (ValueError, TypeError):
                        logger.warning("task_event_listener_bad_message")
                        continue
                    _dispatch_wake(signal.task_id for signal in signals)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 断线重连是监听循环的正常路径
            if stop.is_set():
                break
            logger.warning(
                "task_event_listener_reconnect", error_type=type(exc).__name__
            )
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
        finally:
            for closer in (pubsub, client):
                if closer is not None:
                    with contextlib.suppress(Exception):  # noqa: BLE001
                        await closer.aclose()
    _ = settings


async def start_listener() -> None:
    """进程级订阅任务；未启用 Redis 时不启动。"""
    global _listener_task, _stop_event
    settings = get_settings()
    if not settings.redis_enabled or _listener_task is not None:
        return
    _stop_event = asyncio.Event()
    _listener_task = asyncio.create_task(_listen_loop(_stop_event), name="task-event-listener")


async def stop_listener() -> None:
    global _listener_task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _listener_task is not None:
        _listener_task.cancel()
        try:
            await _listener_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _listener_task = None
    _stop_event = None
