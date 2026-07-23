export const SITE_TIME_ZONE = 'Asia/Shanghai';

const shanghaiDateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: SITE_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

export function formatShanghaiDateTime(
  value: string | number | Date,
  fallback = '未知',
): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return shanghaiDateTimeFormatter.format(date).replaceAll('/', '-');
}
