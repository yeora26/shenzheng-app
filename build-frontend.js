const fs = require('fs');
const path = require('path');

const rootDir = __dirname;
const distDir = path.join(rootDir, 'dist');

// 清理或创建 dist 目录
if (fs.existsSync(distDir)) {
  fs.rmSync(distDir, { recursive: true, force: true });
}
fs.mkdirSync(distDir, { recursive: true });

// 复制单个文件
function copyFile(src, dest) {
  if (fs.existsSync(src)) {
    fs.copyFileSync(src, dest);
  }
}

// 复制目录
function copyDir(src, dest) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(dest, { recursive: true });
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

copyFile(path.join(rootDir, 'index.html'), path.join(distDir, 'index.html'));
copyFile(path.join(rootDir, 'result.html'), path.join(distDir, 'result.html'));
copyDir(path.join(rootDir, 'assets'), path.join(distDir, 'assets'));

console.log('前端静态文件已成功同步至 dist/ 目录');
