(function () {
  if (document.querySelector("[data-site-nav]")) {
    return;
  }

  var script = document.currentScript;
  var scriptUrl = script ? new URL(script.getAttribute("src"), document.baseURI) : new URL("./assets/site-nav.js", document.baseURI);
  var siteRoot = new URL("../", scriptUrl);
  var rootPath = siteRoot.pathname.endsWith("/") ? siteRoot.pathname : siteRoot.pathname + "/";
  var currentPath = window.location.pathname.replace(/\/index\.html$/, "/");
  var relativePath = currentPath.indexOf(rootPath) === 0 ? currentPath.slice(rootPath.length) : currentPath.replace(/^\//, "");

  function href(path) {
    return new URL(path, siteRoot).href;
  }

  function isCurrent(path) {
    var target = new URL(path, siteRoot).pathname.replace(/\/index\.html$/, "/");
    return currentPath === target;
  }

  function link(label, path) {
    var active = isCurrent(path);
    return '<a class="site-nav__link' + (active ? " is-current" : "") + '" href="' + href(path) + '"' + (active ? ' aria-current="page"' : "") + ">" + label + "</a>";
  }

  function contextLink() {
    if (relativePath.indexOf("reports/crowdsourcing-memory-analysis/") === 0 && !isCurrent("reports/crowdsourcing-memory-analysis/")) {
      return '<a class="site-nav__context" href="' + href("reports/crowdsourcing-memory-analysis/") + '">返回众包内存分析</a>';
    }
    if (relativePath.indexOf("reports/cangjie-language-analysis/") === 0 && !isCurrent("reports/cangjie-language-analysis/")) {
      return '<a class="site-nav__context" href="' + href("reports/cangjie-language-analysis/") + '">返回仓颉语言分析</a>';
    }
    if (relativePath.indexOf("reports/auto/") === 0 && !isCurrent("reports/auto/")) {
      return '<a class="site-nav__context" href="' + href("reports/auto/") + '">返回自动报告</a>';
    }
    if (relativePath.indexOf("reports/aar-issue-917/") === 0 && !isCurrent("reports/aar-issue-917/")) {
      return '<a class="site-nav__context" href="' + href("reports/aar-issue-917/") + '">返回 AAR 报告</a>';
    }
    if (!isCurrent("")) {
      return '<a class="site-nav__context" href="' + href("") + '">返回报告中心</a>';
    }
    return '<span class="site-nav__context is-static">报告中心</span>';
  }

  var style = document.createElement("style");
  style.textContent = [
    ".site-nav{position:sticky;top:0;z-index:2147483000;background:rgba(255,255,255,.96);border-bottom:1px solid #d9e1e8;box-shadow:0 1px 8px rgba(23,33,43,.06);backdrop-filter:saturate(1.2) blur(8px);font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",\"PingFang SC\",\"Hiragino Sans GB\",\"Microsoft YaHei\",sans-serif;color:#17212b}",
    ".site-nav__inner{max-width:1180px;margin:0 auto;padding:9px 18px;display:flex;align-items:center;gap:12px}",
    ".site-nav__brand{font-weight:800;color:#0f5f5f;text-decoration:none;white-space:nowrap}",
    ".site-nav__links{display:flex;align-items:center;gap:6px;flex-wrap:wrap}",
    ".site-nav__link,.site-nav__context{display:inline-flex;align-items:center;min-height:32px;border-radius:8px;padding:5px 10px;color:#34495e;text-decoration:none;font-size:13px;font-weight:650;line-height:1.25}",
    ".site-nav__link:hover,.site-nav__context:hover{background:#eef8f6;color:#075f5f}",
    ".site-nav__link.is-current{background:#0f7b7b;color:#fff}",
    ".site-nav__spacer{flex:1 1 auto}",
    ".site-nav__context{border:1px solid #b9dcd5;background:#f7fbfa;color:#075f5f}",
    ".site-nav__context.is-static{border-color:transparent;background:transparent;color:#5d6875}",
    "@media(max-width:760px){.site-nav__inner{align-items:flex-start;flex-direction:column;gap:7px}.site-nav__links{width:100%;overflow-x:auto;flex-wrap:nowrap;padding-bottom:2px}.site-nav__link,.site-nav__context{white-space:nowrap}.site-nav__spacer{display:none}}"
  ].join("");
  document.head.appendChild(style);

  var nav = document.createElement("nav");
  nav.className = "site-nav";
  nav.setAttribute("data-site-nav", "true");
  nav.setAttribute("aria-label", "报告站点导航");
  nav.innerHTML =
    '<div class="site-nav__inner">' +
    '<a class="site-nav__brand" href="' + href("") + '">报告中心</a>' +
    '<div class="site-nav__links">' +
    link("仓颉语言分析", "reports/cangjie-language-analysis/") +
    link("众包内存分析", "reports/crowdsourcing-memory-analysis/") +
    link("AAR 复盘", "reports/aar-issue-917/") +
    link("自动报告", "reports/auto/") +
    "</div>" +
    '<span class="site-nav__spacer"></span>' +
    contextLink() +
    "</div>";

  document.body.insertBefore(nav, document.body.firstChild);
}());
