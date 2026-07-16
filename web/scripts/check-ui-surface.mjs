import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const root = process.cwd();
const dashboard = fs.readFileSync(path.join(root, 'app/dashboard/page.tsx'), 'utf8');
const admin = fs.readFileSync(path.join(root, 'app/admin/config/page.tsx'), 'utf8');

const failures = [];

if (!dashboard.includes('loading && !hasLoaded')) {
  failures.push('Dashboard refresh must not reuse the initial full-screen “正在进入” overlay.');
}
if (dashboard.includes('作品索引') || dashboard.includes('CatalogCard')) {
  failures.push('Dashboard must not render or define the work-index UI.');
}
if (/type AdminTab[^\n]*'library'/.test(admin) || admin.includes("key: 'library'") || admin.includes('媒体库浏览')) {
  failures.push('Admin console must not expose the media-library tab/browser.');
}
if (admin.includes('label="媒体库"') || admin.includes('媒体库浏览') || admin.includes("key: 'library'")) {
  failures.push('Admin console must not expose media-library stats, cards, or the browser tab.');
}
if (!admin.includes('前台展示') || !admin.includes('客户端与下载') || !admin.includes('运营设置')) {
  failures.push('Admin settings must be grouped by purpose.');
}
for (const staleLabel of ['客户端服务地址', 'Android 直装链接', 'iOS 教程说明', '电脑端教程说明']) {
  if (admin.includes(`label="${staleLabel}"`)) failures.push(`Admin settings still use stale label: ${staleLabel}`);
}
if (!dashboard.includes('下载 Android 安装包') || dashboard.includes('直装安装包：')) {
  failures.push('Android package must be a direct action, not a copied URL inside tutorial text.');
}
if ((dashboard.match(/添加服务器地址/g) || []).length > 0 || (dashboard.match(/服务器地址：\$\{serverAddress\}/g) || []).length > 0) {
  failures.push('Tutorial cards must not repeat the server address shown in the shared address card.');
}

if (failures.length) {
  console.error(failures.map((failure) => `- ${failure}`).join('\n'));
  process.exit(1);
}

console.log('UI surface checks passed.');
