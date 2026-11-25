(function () {
  const openBtn = document.getElementById("open");
  const refreshBtn = document.getElementById("refresh");
  const filterInput = document.getElementById("filter");
  const folderLabel = document.getElementById("folders");
  const countLabel = document.getElementById("count");
  const list = document.getElementById("list");
  const pauseBtn = document.getElementById("pause");
  const loopBtn = document.getElementById("loop");
  const skinWrap = document.getElementById("skinWrap");
  const skinSelect = document.getElementById("skin");
  const pmaBox = document.getElementById("pma");
  const nowLabel = document.getElementById("now");
  const anims = document.getElementById("anims");
  const frame = document.getElementById("frame");
  const overlay = document.getElementById("overlay");
  const zoomOutBtn = document.getElementById("zoomOut");
  const zoomResetBtn = document.getElementById("zoomReset");
  const zoomInBtn = document.getElementById("zoomIn");
  const viewHint = document.getElementById("viewHint");

  let payload = { assets: [], folders: [], scanning: false, supported: [] };
  let current = null;
  let token = 0;
  let frameRuntime = "";
  let frameReady = false;
  let frameSeq = 0;
  let pendingReady = null;
  let pendingFail = null;
  const pmaOverride = new Map();
  let pollTimer = 0;
  let librarySignature = "";
  let folderSignature = "";

  function showOverlay(text) {
    overlay.textContent = text;
    overlay.classList.remove("hidden");
  }

  function hideOverlay() {
    overlay.classList.add("hidden");
  }

  function setPlaying(on) {
    pauseBtn.disabled = !on;
    loopBtn.disabled = !on;
    zoomOutBtn.disabled = !on;
    zoomInBtn.disabled = !on;
    zoomResetBtn.disabled = !on;
    viewHint.classList.toggle("hidden", !on);
    if (!on) {
      pauseBtn.textContent = "暂停";
      loopBtn.classList.remove("on");
      nowLabel.textContent = "";
      zoomResetBtn.textContent = "100%";
    }
  }

  function postFrame(message) {
    if (!frame.contentWindow) return;
    frame.contentWindow.postMessage(message, location.origin);
  }

  function renderList() {
    const query = filterInput.value.trim().toLowerCase();
    const assets = payload.assets || [];
    const folders = payload.folders || [];
    const folderNames = new Map(folders.map(function (folder) { return [folder.id, folder.name]; }));
    const signature = JSON.stringify([query, folders, assets, payload.scanning, payload.pending,
      payload.error, payload.warning, current ? current.id : ""]);
    if (signature === librarySignature) return;
    const scrollTop = list.scrollTop;
    librarySignature = signature;
    const shown = assets.filter(function (asset) {
      if (!query) return true;
      const source = folderNames.get(asset.source) || "";
      return (source + " " + asset.rel + " " + asset.kind + " " + asset.version).toLowerCase().indexOf(query) >= 0;
    });
    countLabel.textContent = payload.scanning
      ? shown.length + " 个资源 · 正在扫描 " + (payload.pending || []).join("、") + "…"
      : (folders.length + " 个文件夹 · " + shown.length + " / " + assets.length + " 个资源");
    list.replaceChildren();
    if (!folders.length) return;
    if (payload.scanning && !assets.length) {
      const note = document.createElement("div");
      note.className = "empty";
      note.textContent = "正在查找 .skel 和 .json…";
      list.appendChild(note);
    }
    if (!payload.scanning && !assets.length) {
      const note = document.createElement("div");
      note.className = "empty";
      note.textContent = payload.error || "没有找到 Spine 文件。需要 .skel 或 .json，以及同目录的 .atlas。";
      list.appendChild(note);
      return;
    }
    let previousSource = "";
    shown.forEach(function (asset) {
      if (asset.source !== previousSource) {
        const heading = document.createElement("div");
        const folder = folders.find(function (item) { return item.id === asset.source; });
        heading.className = "source";
        heading.textContent = folderNames.get(asset.source) || "已添加文件夹";
        heading.title = folder ? folder.path : "";
        list.appendChild(heading);
        previousSource = asset.source;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "file" + (current && current.id === asset.id ? " on" : "");
      button.title = (folderNames.get(asset.source) || "") + " / " + asset.rel;
      const name = document.createElement("span");
      name.className = "file-name";
      name.textContent = asset.name;
      const meta = document.createElement("span");
      meta.className = "file-meta";
      const where = asset.dir || "根目录";
      const version = asset.version || "未知版本";
      meta.textContent = where + " · " + asset.kind + " · " + version + (asset.runtime ? "" : " · 未支持");
      button.appendChild(name);
      button.appendChild(meta);
      button.addEventListener("click", function () { selectAsset(asset); });
      list.appendChild(button);
    });
    if (!payload.scanning && query && !shown.length) {
      const note = document.createElement("div");
      note.className = "empty";
      note.textContent = "没有匹配的资源。";
      list.appendChild(note);
    }
    if (payload.warning && !payload.scanning) {
      const note = document.createElement("div");
      note.className = "empty";
      note.textContent = payload.warning;
      list.appendChild(note);
    }
    if (current) {
      const selected = list.querySelector(".file.on");
      if (selected && selected.getBoundingClientRect().bottom > list.getBoundingClientRect().bottom) {
        selected.scrollIntoView({ block: "nearest" });
      } else {
        list.scrollTop = scrollTop;
      }
    } else {
      list.scrollTop = scrollTop;
    }
  }

  function buildAnims(names) {
    anims.replaceChildren();
    names.forEach(function (name) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn anim";
      button.dataset.name = name;
      button.title = name;
      button.textContent = name;
      button.addEventListener("click", function () {
        postFrame({ type: "playOne", name: name });
      });
      anims.appendChild(button);
    });
  }

  function applyState(state) {
    pauseBtn.textContent = state.paused ? "继续" : "暂停";
    loopBtn.classList.toggle("on", !!state.loopAll);
    nowLabel.textContent = state.current ? ("正在播放 " + state.current) : "";
    anims.querySelectorAll("button").forEach(function (button) {
      const on = button.dataset.name === state.current;
      button.classList.toggle("on", on);
      if (on) button.scrollIntoView({ block: "nearest" });
    });
  }

  function fillSkins(skins) {
    skinSelect.replaceChildren();
    if (!skins || skins.length < 2) {
      skinWrap.hidden = true;
      return;
    }
    skins.forEach(function (name) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      skinSelect.appendChild(option);
    });
    skinWrap.hidden = false;
  }

  function ensureFrame(runtime) {
    if (frameRuntime === runtime && frameReady) return Promise.resolve();
    const seq = ++frameSeq;
    frameReady = false;
    frameRuntime = runtime;
    return new Promise(function (resolve, reject) {
      const timer = setTimeout(function () {
        if (seq !== frameSeq) return;
        reject(new Error("运行时加载超时"));
      }, 20000);
      pendingReady = function () {
        if (seq !== frameSeq) return;
        clearTimeout(timer);
        frameReady = true;
        resolve();
      };
      pendingFail = function (message) {
        if (seq !== frameSeq) return;
        clearTimeout(timer);
        reject(new Error(message || "运行时加载失败"));
      };
      frame.src = "/player.html?runtime=" + encodeURIComponent(runtime) + "&r=" + seq;
    });
  }

  async function selectAsset(asset) {
    const my = ++token;
    current = asset;
    pmaBox.disabled = false;
    pmaBox.checked = pmaOverride.has(asset.id) ? pmaOverride.get(asset.id) : !!asset.pma;
    renderList();
    anims.replaceChildren();
    fillSkins([]);
    setPlaying(false);
    if (!asset.runtime) {
      const supported = (payload.supported || []).join("、") || "无";
      showOverlay("Spine " + (asset.version || "未知版本") + " 还不能播放。\n当前运行时：" + supported);
      return;
    }
    if (!asset.atlasUrl) {
      showOverlay("同目录没有找到配套的 .atlas。");
      return;
    }
    showOverlay("正在加载…");
    try {
      await ensureFrame(asset.runtime);
    } catch (err) {
      if (my === token) showOverlay(err.message || "运行时加载失败");
      return;
    }
    if (my !== token) return;
    postFrame({
      type: "load",
      token: my,
      asset: {
        skeletonUrl: asset.skeletonUrl,
        atlasUrl: asset.atlasUrl,
        kind: asset.kind,
        pma: pmaBox.checked,
      },
    });
  }

  let refreshBusy = false;
  let failures = 0;

  // A hanging socket must never wedge the poll loop, so every request gets
  // its own deadline instead of waiting on the browser's default timeout.
  async function getJson(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, 6000);
    try {
      const response = await fetch(url, Object.assign({
        signal: controller.signal,
        cache: "no-store",
      }, options || {}));
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function refresh() {
    if (refreshBusy) return;
    refreshBusy = true;
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = 0;
    }
    try {
      const data = await getJson("/api/assets");
      failures = 0;
      payload = data;
      const folders = data.folders || [];
      const nextFolderSignature = JSON.stringify(folders);
      if (nextFolderSignature !== folderSignature) {
        folderSignature = nextFolderSignature;
        folderLabel.replaceChildren();
        if (!folders.length) {
          folderLabel.textContent = "尚未添加文件夹";
        } else {
          folders.forEach(function (folder) {
            const item = document.createElement("div");
            item.className = "folder";
            item.textContent = folder.name;
            item.title = folder.path;
            folderLabel.appendChild(item);
          });
        }
      }
      if (data.dropError) countLabel.textContent = data.dropError;
      renderList();
      pollTimer = setTimeout(refresh, data.scanning ? 400 : 1200);
      if (data.scanning) return;
      if (!folders.length) {
        showOverlay("把文件夹拖到左侧区域，或点击「添加文件夹」。\n可分多次添加不同文件夹，所有 Spine 动画都会保留在同一个列表中。");
        return;
      }
      if (data.selected) {
        const selected = (data.assets || []).find(function (asset) { return asset.id === data.selected; });
        if (selected && (!current || current.id !== selected.id)) selectAsset(selected);
      }
    } catch (err) {
      // keep polling: a dead window that never retries stays stuck on "加载中"
      failures += 1;
      countLabel.textContent = failures > 3
        ? "连接查看器失败，请重启程序。"
        : "正在重新连接查看器…";
      pollTimer = setTimeout(refresh, failures > 3 ? 5000 : 1000);
    } finally {
      refreshBusy = false;
    }
  }

  openBtn.addEventListener("click", async function () {
    openBtn.disabled = true;
    try {
      await getJson("/api/folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      await refresh();
    } catch (err) {
      countLabel.textContent = "添加文件夹失败，请重试。";
    } finally {
      openBtn.disabled = false;
    }
  });

  // Windows folder paths arrive through the local native drop helper.
  ["dragenter", "dragover"].forEach(function (name) {
    document.addEventListener(name, function (event) {
      event.preventDefault();
      document.body.classList.add("drag-over");
    });
  });
  document.addEventListener("dragleave", function (event) {
    if (!event.relatedTarget) document.body.classList.remove("drag-over");
  });
  document.addEventListener("drop", function (event) {
    event.preventDefault();
    document.body.classList.remove("drag-over");
    // Chromium keeps directory paths private; /api/drop handles native paths.
  });

  refreshBtn.addEventListener("click", async function () {
    try {
      const response = await getJson("/api/rescan", { method: "POST" });
      if (!response.ok) return;
    } catch (err) {
      countLabel.textContent = "刷新失败，请重试。";
      return;
    }
    showOverlay("正在重新扫描全部文件夹…");
    await refresh();
  });

  filterInput.addEventListener("input", renderList);
  pauseBtn.addEventListener("click", function () {
    postFrame({ type: "togglePause" });
  });
  loopBtn.addEventListener("click", function () {
    postFrame({ type: "loop" });
  });
  zoomOutBtn.addEventListener("click", function () {
    postFrame({ type: "zoomOut" });
  });
  zoomInBtn.addEventListener("click", function () {
    postFrame({ type: "zoomIn" });
  });
  zoomResetBtn.addEventListener("click", function () {
    postFrame({ type: "zoomReset" });
  });
  skinSelect.addEventListener("change", function () {
    postFrame({ type: "skin", name: skinSelect.value });
  });
  pmaBox.addEventListener("change", function () {
    if (!current) return;
    pmaOverride.set(current.id, pmaBox.checked);
    selectAsset(current);
  });

  window.addEventListener("message", function (event) {
    if (event.origin !== location.origin) return;
    const data = event.data || {};
    if (data.type === "runtime-ready" && data.runtime === frameRuntime && pendingReady) pendingReady();
    if (data.type === "runtime-failed" && data.runtime === frameRuntime && pendingFail) pendingFail(data.message);
    if (data.token != null && data.token !== token) return;
    if (data.type === "loaded") {
      hideOverlay();
      setPlaying(true);
      buildAnims(data.animations || []);
      fillSkins(data.skins || []);
    } else if (data.type === "state") {
      applyState(data);
    } else if (data.type === "view") {
      zoomResetBtn.textContent = Math.round((data.zoom || 1) * 100) + "%";
    } else if (data.type === "error") {
      setPlaying(false);
      showOverlay(data.message || "加载失败");
    }
  });

  window.addEventListener("keydown", function (event) {
    const tag = event.target && event.target.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || tag === "BUTTON") return;
    if (pauseBtn.disabled) return;
    if (event.code === "Space") {
      event.preventDefault();
      postFrame({ type: "togglePause" });
      return;
    }
    if (event.key === "+" || event.key === "=" || event.code === "NumpadAdd") {
      event.preventDefault();
      postFrame({ type: "zoomIn" });
    } else if (event.key === "-" || event.code === "NumpadSubtract") {
      event.preventDefault();
      postFrame({ type: "zoomOut" });
    } else if (event.key === "0" || event.code === "Numpad0") {
      event.preventDefault();
      postFrame({ type: "zoomReset" });
    }
  });

  function beat() {
    fetch("/api/heartbeat", { cache: "no-store" }).catch(function () {});
  }

  // Coming back from the background: ping right away and repaint the list,
  // because pending timers may have been frozen while the window was hidden.
  function wake() {
    if (document.hidden) return;
    beat();
    if (!refreshBusy) refresh();
  }

  setInterval(beat, 1000);
  document.addEventListener("visibilitychange", wake);
  window.addEventListener("focus", wake);
  window.addEventListener("pageshow", wake);
  refresh();
})();
