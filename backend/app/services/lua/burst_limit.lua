-- 共享短窗限流（xunke/redis-rate-key/v1 契约的一部分）。
-- 一次原子执行同时检查至多两个桶（IP 与账户）：任一桶已满则整体拒绝且不修改，
-- 全部允许才一起递增。首条写入附带 TTL，后续保持 TTL，不做滑动续期。
-- 输入：KEYS[1..n] 桶键；ARGV[1..n] 为各桶上限；ARGV[n+1] 为窗口毫秒数。
-- 返回：{1, 0} 放行；{0, retry_after_ms} 拒绝（取满桶中最长剩余时间）。
local window = tonumber(ARGV[#KEYS + 1])
if not window or window <= 0 then
  return redis.error_reply('RATE_LIMIT_INVALID_WINDOW')
end
local counts, ttls = {}, {}
local retry_after_ms = 0
for i = 1, #KEYS do
  local limit = tonumber(ARGV[i])
  if not limit or limit <= 0 then
    return redis.error_reply('RATE_LIMIT_INVALID_LIMIT')
  end
  counts[i] = tonumber(redis.call('GET', KEYS[i]) or '0')
  ttls[i] = redis.call('PTTL', KEYS[i])
  if ttls[i] == -1 then
    -- 无过期时间的持久键意味着配置错误：拒绝执行而不是放行。
    return redis.error_reply('RATE_LIMIT_KEY_WITHOUT_TTL')
  end
  if counts[i] >= limit then
    local remaining = math.max(1, ttls[i])
    if remaining > retry_after_ms then
      retry_after_ms = remaining
    end
  end
end
if retry_after_ms > 0 then
  return {0, retry_after_ms}
end
for i = 1, #KEYS do
  if ttls[i] == -2 then
    redis.call('SET', KEYS[i], 1, 'PX', window)
  else
    redis.call('INCR', KEYS[i])
  end
end
return {1, 0}
