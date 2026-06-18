# 仓颉语言优势报告静态站点

这是一个可直接发布到云端的静态报告中心。站点入口为 `index.html`，当前包含“仓颉语言分析”“众包内存分析”和“AAR 复盘报告”三类报告。

## 目录说明

- `index.html`：报告中心入口，部署后访问站点根路径即可打开。
- `reports/cangjie-language-analysis/`：仓颉语言分析报告。
- `reports/crowdsourcing-memory-analysis/`：众包内存分析报告。
- `reports/aar-issue-917/`：release/1.0 部分用例 ICE 11 的 AAR 复盘报告。
- `cangjie_domain_advantages_report.html`：早期报告备份文件，便于保留原始报告文件名。
- `_headers`：Cloudflare Pages / Netlify 等静态托管平台可识别的缓存与安全响应头。
- `404.html`：静态托管平台的兜底页面，会引导访问者回到报告首页。

## 推荐发布方式

### 方式一：Cloudflare Pages

1. 新建 Pages 项目。
2. 选择上传静态资源目录。
3. 上传本目录 `cangjie-report-site` 中的全部文件。
4. 部署完成后，访问 Cloudflare 分配的域名即可分享给同事。

### 方式二：GitHub Pages

1. 新建一个仓库，例如 `cangjie-report-site`。
2. 将本目录中的文件放到仓库根目录。
3. 在仓库 Settings -> Pages 中选择从默认分支根目录发布。
4. 发布完成后使用 GitHub Pages 地址分享。

### 方式三：公司内网 / Nginx / 对象存储

将本目录作为静态站点根目录发布即可。确保 `index.html` 位于站点根路径。

## 本地预览

在本目录运行：

```sh
python3 -m http.server 8077 --bind 127.0.0.1
```

然后访问：

```text
http://127.0.0.1:8077/
```
