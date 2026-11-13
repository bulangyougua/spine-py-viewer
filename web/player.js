(function () {
  const params = new URLSearchParams(location.search);
  const runtime = params.get("runtime") || "";
  const host = document.getElementById("host");
  let player = null;
  let names = [];
  let index = 0;
  let current = "";
  let loopAll = false;
  let paused = false;
  let activeToken = 0;
  let rafId = 0;
  const view = { zoom: 1, panX: 0, panY: 0, touched: false, refit: false };
  const zoomMin = 0.08;
  const zoomMax = 16;
  let yDown = false;
  let fit21 = null;

  function post(message) {
    message.token = activeToken;
    message.runtime = runtime;
    parent.postMessage(message, location.origin);
  }

  function postState() {
    post({ type: "state", paused: paused, loopAll: loopAll, current: current });
  }

  function postView() {
    post({ type: "view", zoom: view.zoom });
  }

  function clampZoom(value) {
    return Math.max(zoomMin, Math.min(zoomMax, value));
  }

  function resetView() {
    view.zoom = 1;
    view.panX = 0;
    view.panY = 0;
    view.touched = false;
    view.refit = true;
    postView();
  }

  function markView() {
    view.touched = true;
    view.refit = false;
  }

  function zoomBy(factor, u, v) {
    const next = clampZoom(view.zoom * factor);
    if (next === view.zoom) return;
    const yOf = yDown ? (v - 0.5) : (0.5 - v);
    const ox = (u - 0.5) / view.zoom;
    const oy = yOf / view.zoom;
    view.zoom = next;
    view.panX += ox - (u - 0.5) / next;
    view.panY += oy - yOf / next;
    markView();
    postView();
  }

  function panBy(dx, dy, width, height) {
    if (!width || !height) return;
    view.panX -= dx / width / view.zoom;
    view.panY += (yDown ? -dy : dy) / height / view.zoom;
    markView();
  }

  function transformViewport(fit) {
    const padLeft = +fit.padLeft || 0;
    const padRight = +fit.padRight || 0;
    const padTop = +fit.padTop || 0;
    const padBottom = +fit.padBottom || 0;
    const width = fit.width + padLeft + padRight;
    const height = fit.height + padTop + padBottom;
    const x = fit.x - padLeft;
    const y = fit.y - padBottom;
    const cx = x + width / 2 + view.panX * width;
    const cy = y + height / 2 + view.panY * height;
    const w = width / view.zoom;
    const h = height / view.zoom;
    return {
      x: cx - w / 2,
      y: cy - h / 2,
      width: w,
      height: h,
      padLeft: 0,
      padRight: 0,
      padTop: 0,
      padBottom: 0,
    };
  }

  function hookPlayer(spinePlayer) {
    const original = spinePlayer.drawFrame;
    if (typeof original !== "function") return;
    spinePlayer.drawFrame = function (requestNextFrame) {
      const fit = spinePlayer.currentViewport;
      const custom = fit && fit.width > 0 && fit.height > 0 && (view.zoom !== 1 || view.panX || view.panY);
      if (!custom) return original.call(spinePlayer, requestNextFrame);
      const saved = fit;
      spinePlayer.previousViewport = null;
      spinePlayer.currentViewport = transformViewport(saved);
      try {
        return original.call(spinePlayer, requestNextFrame);
      } finally {
        spinePlayer.currentViewport = saved;
      }
    };
  }

  function bindViewInput() {
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    window.addEventListener("wheel", function (event) {
      if (!player) return;
      event.preventDefault();
      const rect = host.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const u = (event.clientX - rect.left) / rect.width;
      const v = (event.clientY - rect.top) / rect.height;
      const dy = Math.max(-240, Math.min(240, event.deltaY));
      zoomBy(Math.exp(-dy * 0.0016), u, v);
    }, { passive: false, capture: true });
    window.addEventListener("pointerdown", function (event) {
      if (!player || event.button !== 0) return;
      dragging = true;
      lastX = event.clientX;
      lastY = event.clientY;
      document.documentElement.classList.add("dragging");
      if (event.target.setPointerCapture) {
        try { event.target.setPointerCapture(event.pointerId); } catch (err) { /* canvas may reject */ }
      }
    }, true);
    window.addEventListener("pointermove", function (event) {
      if (!dragging || !player) return;
      const rect = host.getBoundingClientRect();
      panBy(event.clientX - lastX, event.clientY - lastY, rect.width, rect.height);
      lastX = event.clientX;
      lastY = event.clientY;
    }, true);
    function endDrag() {
      dragging = false;
      document.documentElement.classList.remove("dragging");
    }
    window.addEventListener("pointerup", endDrag, true);
    window.addEventListener("pointercancel", endDrag, true);
    window.addEventListener("dblclick", function (event) {
      if (!player) return;
      event.preventDefault();
      resetView();
    }, true);
  }

  function readNames(skeleton) {
    const anims = (skeleton && skeleton.data && skeleton.data.animations) || [];
    const out = [];
    for (let i = 0; i < anims.length; i++) {
      if (anims[i] && anims[i].name) out.push(anims[i].name);
    }
    return out;
  }

  function readSkins(skeleton) {
    const skins = (skeleton && skeleton.data && skeleton.data.skins) || [];
    const out = [];
    for (let i = 0; i < skins.length; i++) {
      if (skins[i] && skins[i].name) out.push(skins[i].name);
    }
    return out;
  }

  function stopLoop() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
  }

  function disposeCurrent() {
    stopLoop();
    if (player && typeof player.dispose === "function") {
      try { player.dispose(); } catch (err) { /* context already gone */ }
    }
    player = null;
    host.replaceChildren();
  }

  function setPaused(value) {
    paused = value;
    if (player) {
      if (value && typeof player.pause === "function") player.pause();
      else if (!value && typeof player.play === "function") player.play();
      else player.paused = value;
    }
    postState();
  }

  function setAnim(name, loop) {
    if (!player || !name) return;
    let entry = null;
    if (typeof player.setAnimation === "function") entry = player.setAnimation(name, loop);
    else if (player.animationState) entry = player.animationState.setAnimation(0, name, loop);
    if (entry) {
      entry.loop = loop;
      if ("mixDuration" in entry) entry.mixDuration = 0;
    }
    current = name;
    index = names.indexOf(name);
    if (index < 0) index = 0;
    postState();
  }

  function startLoop() {
    if (!names.length) return;
    loopAll = true;
    setPaused(false);
    setAnim(names[0], false);
  }

  function playOne(name) {
    if (!names.length) return;
    loopAll = false;
    setPaused(false);
    setAnim(name, false);
  }

  function onComplete(entry, owned) {
    if (player !== owned || !loopAll || paused) return;
    const name = entry && entry.animation && entry.animation.name;
    if (name !== current) return;
    const next = (index + 1) % names.length;
    setTimeout(function () {
      if (player !== owned || !loopAll || paused || current !== name) return;
      setAnim(names[next], false);
    }, 0);
  }

  function onReady(nextPlayer) {
    player = nextPlayer;
    names = readNames(nextPlayer.skeleton);
    if (!names.length) {
      post({ type: "error", message: "这个文件里没有动画" });
      return;
    }
    if (nextPlayer.animationState && nextPlayer.animationState.addListener) {
      nextPlayer.animationState.addListener({
        complete: function (entry) { onComplete(entry, nextPlayer); },
      });
    }
    post({ type: "loaded", animations: names, skins: readSkins(nextPlayer.skeleton) });
    startLoop();
  }

  function makeCanvas() {
    const canvas = document.createElement("canvas");
    host.appendChild(canvas);
    return canvas;
  }

  function loadPlayer(asset) {
    if (!window.spine || !window.spine.SpinePlayer) {
      post({ type: "error", message: "Spine " + runtime + " 运行时不可用" });
      return;
    }
    const useV4 = runtime.startsWith("4.");
    const config = {
      showControls: false,
      premultipliedAlpha: !!asset.pma,
      defaultMix: 0,
      backgroundColor: useV4 ? "#00000000" : "#000000",
      success: onReady,
      error: function (_player, msg) {
        post({ type: "error", message: String(msg || "加载失败") });
      },
    };
    if (useV4) {
      config.alpha = true;
      config.preserveDrawingBuffer = false;
      config.viewport = {
        padLeft: "8%",
        padRight: "8%",
        padTop: "8%",
        padBottom: "8%",
        transitionTime: 0,
      };
      config.skeleton = asset.skeletonUrl;
      config.atlas = asset.atlasUrl;
      config.atlasUrl = asset.atlasUrl;
      if (asset.kind === "skel") {
        config.binaryUrl = asset.skeletonUrl;
        config.skelUrl = asset.skeletonUrl;
      } else {
        config.jsonUrl = asset.skeletonUrl;
      }
    } else {
      config.atlasUrl = asset.atlasUrl;
      config.viewport = {
        padLeft: "8%",
        padRight: "8%",
        padTop: "8%",
        padBottom: "8%",
        transitionTime: 0,
      };
      if (asset.kind === "skel") config.skelUrl = asset.skeletonUrl;
      else config.jsonUrl = asset.skeletonUrl;
    }
    try {
      player = new spine.SpinePlayer(host, config);
      hookPlayer(player);
    } catch (err) {
      post({ type: "error", message: String(err && err.message || err) });
    }
  }

  function load36(asset) {
    const canvas = makeCanvas();
    let context = null;
    try {
      context = new spine.webgl.ManagedWebGLRenderingContext(canvas, {
        alpha: true,
        premultipliedAlpha: !!asset.pma,
      });
    } catch (err) {
      post({ type: "error", message: "WebGL 不可用" });
      return;
    }
    if (!context.gl) {
      post({ type: "error", message: "WebGL 不可用" });
      return;
    }
    const renderer = new spine.webgl.SceneRenderer(canvas, context);
    const assetManager = new spine.webgl.AssetManager(context);
    const generation = activeToken;
    assetManager.loadText(asset.skeletonUrl);
    assetManager.loadTextureAtlas(asset.atlasUrl);

    function fail(message) {
      if (generation !== activeToken) return;
      post({ type: "error", message: message });
    }

    function finish() {
      if (generation !== activeToken) return;
      if (!assetManager.isLoadingComplete()) {
        requestAnimationFrame(finish);
        return;
      }
      if (assetManager.hasErrors()) {
        const errors = assetManager.getErrors();
        const text = Object.keys(errors).map(function (key) { return errors[key]; }).join("\n");
        fail(text || "贴图或数据加载失败");
        return;
      }
      try {
        const atlas = assetManager.get(asset.atlasUrl);
        const jsonText = assetManager.get(asset.skeletonUrl);
        const skeletonJson = new spine.SkeletonJson(new spine.AtlasAttachmentLoader(atlas));
        const skeletonData = skeletonJson.readSkeletonData(JSON.parse(jsonText));
        const skeleton = new spine.Skeleton(skeletonData);
        const stateData = new spine.AnimationStateData(skeletonData);
        stateData.defaultMix = 0;
        const animationState = new spine.AnimationState(stateData);
        skeleton.setToSetupPose();
        skeleton.updateWorldTransform();
        const offset = new spine.Vector2();
        const size = new spine.Vector2();
        skeleton.getBounds(offset, size, []);
        if (!(size.x > 1) || !(size.y > 1)) {
          offset.x = -200;
          offset.y = -200;
          size.x = 400;
          size.y = 400;
        }
        const fit = { cx: 0, cy: 0, w: 400, h: 400, ready: false };
        function takeBounds(replace) {
          skeleton.getBounds(offset, size, []);
          if (!(size.x > 1) || !(size.y > 1)) {
            if (!fit.ready) {
              fit.cx = 0;
              fit.cy = 0;
              fit.w = 400;
              fit.h = 400;
              fit.ready = true;
            }
            return;
          }
          const pad = 1.2;
          const left = offset.x - size.x * (pad - 1) / 2;
          const right = offset.x + size.x * (1 + (pad - 1) / 2);
          const bottom = offset.y - size.y * (pad - 1) / 2;
          const top = offset.y + size.y * (1 + (pad - 1) / 2);
          if (!fit.ready || replace) {
            fit.cx = (left + right) / 2;
            fit.cy = (bottom + top) / 2;
            fit.w = Math.max(right - left, 1);
            fit.h = Math.max(top - bottom, 1);
            fit.ready = true;
            return;
          }
          if (view.touched) return;
          const nextLeft = Math.min(fit.cx - fit.w / 2, left);
          const nextRight = Math.max(fit.cx + fit.w / 2, right);
          const nextBottom = Math.min(fit.cy - fit.h / 2, bottom);
          const nextTop = Math.max(fit.cy + fit.h / 2, top);
          fit.cx = (nextLeft + nextRight) / 2;
          fit.cy = (nextBottom + nextTop) / 2;
          fit.w = nextRight - nextLeft;
          fit.h = nextTop - nextBottom;
        }
        function applyCamera() {
          const replace = view.refit;
          if (replace) view.refit = false;
          takeBounds(replace || !fit.ready);
          const cam = renderer.camera;
          cam.zoom = 1;
          cam.position.x = fit.cx;
          cam.position.y = fit.cy;
          cam.viewportWidth = fit.w;
          cam.viewportHeight = fit.h;
          renderer.resize(spine.webgl.ResizeMode.Fit);
          cam.zoom = 1 / view.zoom;
          cam.position.x = fit.cx + view.panX * cam.viewportWidth;
          cam.position.y = fit.cy + view.panY * cam.viewportHeight;
          cam.update();
        }
        const wrapper = {
          skeleton: skeleton,
          animationState: animationState,
          paused: false,
          setAnimation: function (name, loop) {
            return animationState.setAnimation(0, name, loop);
          },
          pause: function () { wrapper.paused = true; },
          play: function () { wrapper.paused = false; },
          dispose: function () {
            stopLoop();
            const lose = context.gl.getExtension("WEBGL_lose_context");
            if (lose) lose.loseContext();
            assetManager.dispose();
          },
        };
        let last = 0;
        function frame(now) {
          if (player !== wrapper) return;
          rafId = requestAnimationFrame(frame);
          const delta = wrapper.paused || !last ? 0 : Math.min(0.05, (now - last) / 1000);
          last = now;
          animationState.update(delta);
          animationState.apply(skeleton);
          skeleton.updateWorldTransform();
          applyCamera();
          const gl = context.gl;
          gl.clearColor(0, 0, 0, 0);
          gl.clear(gl.COLOR_BUFFER_BIT);
          renderer.begin();
          renderer.drawSkeleton(skeleton, !!asset.pma);
          renderer.end();
        }
        onReady(wrapper);
        rafId = requestAnimationFrame(frame);
      } catch (err) {
        fail(String(err && err.message || err));
      }
    }
    finish();
  }

  function load21(asset) {
    const canvas = makeCanvas();
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      post({ type: "error", message: "无法创建画布" });
      return;
    }
    const generation = activeToken;
    const atlasBase = asset.atlasUrl.slice(0, asset.atlasUrl.lastIndexOf("/") + 1);
    Promise.all([
      fetch(asset.atlasUrl).then(function (res) { if (!res.ok) throw new Error("atlas 加载失败"); return res.text(); }),
      fetch(asset.skeletonUrl).then(function (res) { if (!res.ok) throw new Error("json 加载失败"); return res.text(); }),
    ]).then(function (files) {
      if (generation !== activeToken) return;
      const atlas = new spine.Atlas(files[0], {
        load: function (page, name) {
          const img = new Image();
          img.src = atlasBase + name.split("/").map(encodeURIComponent).join("/");
          page.rendererObject = img;
        },
        unload: function () {},
      });
      const images = atlas.pages.map(function (page) { return page.rendererObject; });
      let left = images.length;
      function ready() {
        if (generation !== activeToken) return;
        try {
          spine.Bone.yDown = true;
          const json = new spine.SkeletonJson(new spine.AtlasAttachmentLoader(atlas));
          const skeletonData = json.readSkeletonData(JSON.parse(files[1]));
          const skeleton = new spine.Skeleton(skeletonData);
          const stateData = new spine.AnimationStateData(skeletonData);
          const animationState = new spine.AnimationState(stateData);
          skeleton.setToSetupPose();
          skeleton.updateWorldTransform();
          const wrapper = {
            skeleton: skeleton,
            animationState: animationState,
            paused: false,
            setAnimation: function (name, loop) {
              return animationState.setAnimationByName(0, name, loop);
            },
            pause: function () { wrapper.paused = true; },
            play: function () { wrapper.paused = false; },
            dispose: stopLoop,
          };
          animationState.onComplete = function () {
            const track = animationState.tracks[0];
            onComplete({ animation: track && track.animation }, wrapper);
          };
          let last = 0;
          function frame(now) {
            if (player !== wrapper) return;
            rafId = requestAnimationFrame(frame);
            const delta = wrapper.paused || !last ? 0 : Math.min(0.05, (now - last) / 1000);
            last = now;
            const width = host.clientWidth || 2;
            const height = host.clientHeight || 2;
            if (canvas.width !== width || canvas.height !== height) {
              canvas.width = width;
              canvas.height = height;
            }
            animationState.update(delta);
            animationState.apply(skeleton);
            skeleton.updateWorldTransform();
            draw21(ctx, canvas, skeleton);
          }
          onReady(wrapper);
          rafId = requestAnimationFrame(frame);
        } catch (err) {
          post({ type: "error", message: String(err && err.message || err) });
        }
      }
      function oneDone() {
        left -= 1;
        if (left <= 0) ready();
      }
      if (!images.length) {
        post({ type: "error", message: "atlas 里没有图片" });
        return;
      }
      images.forEach(function (img) {
        if (img.complete && img.naturalWidth) oneDone();
        else {
          img.onload = oneDone;
          img.onerror = function () {
            if (generation === activeToken) post({ type: "error", message: "贴图加载失败：" + img.src });
          };
        }
      });
    }).catch(function (err) {
      if (generation === activeToken) post({ type: "error", message: String(err && err.message || err) });
    });
  }

  function regionBounds(skeleton) {
    const slots = skeleton.drawOrder;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (let i = 0; i < slots.length; i++) {
      const att = slots[i].attachment;
      if (!(att instanceof spine.RegionAttachment)) continue;
      const bone = slots[i].bone;
      const x = bone.worldX + att.x * bone.m00 + att.y * bone.m01;
      const y = bone.worldY + att.x * bone.m10 + att.y * bone.m11;
      const hw = Math.abs(att.width * att.scaleX) / 2;
      const hh = Math.abs(att.height * att.scaleY) / 2;
      minX = Math.min(minX, x - hw);
      maxX = Math.max(maxX, x + hw);
      minY = Math.min(minY, y - hh);
      maxY = Math.max(maxY, y + hh);
    }
    if (!isFinite(minX) || maxX <= minX || maxY <= minY) return null;
    return { minX: minX, minY: minY, maxX: maxX, maxY: maxY };
  }

  function updateFit21(skeleton) {
    const bounds = regionBounds(skeleton);
    if (!bounds) return;
    const replace = view.refit || !fit21;
    if (view.refit) view.refit = false;
    if (replace) {
      fit21 = bounds;
      return;
    }
    if (view.touched) return;
    fit21 = {
      minX: Math.min(fit21.minX, bounds.minX),
      minY: Math.min(fit21.minY, bounds.minY),
      maxX: Math.max(fit21.maxX, bounds.maxX),
      maxY: Math.max(fit21.maxY, bounds.maxY),
    };
  }

  function draw21(ctx, canvas, skeleton) {
    const slots = skeleton.drawOrder;
    updateFit21(skeleton);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!fit21) return;
    const worldW = Math.max(fit21.maxX - fit21.minX, 1) * 1.2;
    const worldH = Math.max(fit21.maxY - fit21.minY, 1) * 1.2;
    const cx = (fit21.minX + fit21.maxX) / 2 + view.panX * worldW;
    const cy = (fit21.minY + fit21.maxY) / 2 + view.panY * worldH;
    const scale = Math.min(canvas.width / worldW, canvas.height / worldH) * view.zoom;
    ctx.setTransform(scale, 0, 0, scale, canvas.width / 2 - cx * scale, canvas.height / 2 - cy * scale);
    for (let i = 0; i < slots.length; i++) {
      const slot = slots[i];
      const att = slot.attachment;
      if (!(att instanceof spine.RegionAttachment)) continue;
      const region = att.rendererObject;
      const img = region && region.page && region.page.rendererObject;
      if (!img || !img.complete) continue;
      const bone = slot.bone;
      const x = bone.worldX + att.x * bone.m00 + att.y * bone.m01;
      const y = bone.worldY + att.x * bone.m10 + att.y * bone.m11;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(-(bone.worldRotation + att.rotation) * Math.PI / 180);
      ctx.scale(att.scaleX, att.scaleY);
      ctx.globalAlpha = Math.max(0, Math.min(1, slot.a * att.a * skeleton.a));
      ctx.globalCompositeOperation = slot.data.additiveBlending ? "lighter" : "source-over";
      const w = att.width;
      const h = att.height;
      if (region.rotate) {
        ctx.rotate(Math.PI / 2);
        ctx.drawImage(img, region.x, region.y, region.height, region.width, -h / 2, -w / 2, h, w);
      } else {
        ctx.drawImage(img, region.x, region.y, region.width, region.height, -w / 2, -h / 2, w, h);
      }
      ctx.restore();
    }
  }

  function loadAsset(asset, token) {
    activeToken = token || 0;
    loopAll = false;
    paused = false;
    current = "";
    names = [];
    yDown = runtime === "2.1";
    fit21 = null;
    resetView();
    disposeCurrent();
    if (runtime === "3.6") load36(asset);
    else if (runtime === "2.1") load21(asset);
    else loadPlayer(asset);
  }

  function setSkin(name) {
    const skeleton = player && player.skeleton;
    if (!skeleton || !name) return;
    if (typeof skeleton.setSkinByName === "function") skeleton.setSkinByName(name);
    if (typeof skeleton.setSlotsToSetupPose === "function") skeleton.setSlotsToSetupPose();
    if (typeof skeleton.updateWorldTransform === "function") skeleton.updateWorldTransform();
  }

  window.addEventListener("message", function (event) {
    if (event.origin !== location.origin) return;
    const data = event.data || {};
    if (data.type === "load") loadAsset(data.asset || {}, data.token);
    else if (data.type === "togglePause") setPaused(!paused);
    else if (data.type === "loop") startLoop();
    else if (data.type === "playOne") playOne(data.name);
    else if (data.type === "skin") setSkin(data.name);
    else if (data.type === "zoomIn") zoomBy(1.25, 0.5, 0.5);
    else if (data.type === "zoomOut") zoomBy(1 / 1.25, 0.5, 0.5);
    else if (data.type === "zoomReset") resetView();
  });

  window.addEventListener("keydown", function (event) {
    if (!player) return;
    if (event.code === "Space") {
      event.preventDefault();
      setPaused(!paused);
      return;
    }
    if (event.key === "+" || event.key === "=" || event.code === "NumpadAdd") {
      event.preventDefault();
      zoomBy(1.25, 0.5, 0.5);
    } else if (event.key === "-" || event.code === "NumpadSubtract") {
      event.preventDefault();
      zoomBy(1 / 1.25, 0.5, 0.5);
    } else if (event.key === "0" || event.code === "Numpad0") {
      event.preventDefault();
      resetView();
    }
  });

  bindViewInput();

  if (!/^\d+\.\d+$/.test(runtime)) {
    parent.postMessage({ type: "runtime-failed", runtime: runtime, message: "运行时参数无效" }, location.origin);
    return;
  }

  const scriptSrc = runtime === "3.6"
    ? "/vendor/3.6/spine-webgl.js"
    : "/vendor/" + runtime + "/spine-player.js";
  if (runtime !== "3.6" && runtime !== "2.1") {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "/vendor/" + runtime + "/spine-player.css";
    document.head.appendChild(css);
  }
  const script = document.createElement("script");
  script.src = scriptSrc;
  script.onload = function () {
    const ready = runtime === "3.6"
      ? window.spine && window.spine.webgl
      : runtime === "2.1"
        ? window.spine && window.spine.SkeletonJson && window.spine.Atlas
        : window.spine && window.spine.SpinePlayer;
    if (!ready) {
      parent.postMessage({
        type: "runtime-failed",
        runtime: runtime,
        message: "Spine " + runtime + " 运行时不完整",
      }, location.origin);
      return;
    }
    parent.postMessage({ type: "runtime-ready", runtime: runtime }, location.origin);
  };
  script.onerror = function () {
    parent.postMessage({
      type: "runtime-failed",
      runtime: runtime,
      message: "找不到 Spine " + runtime + " 运行时",
    }, location.origin);
  };
  document.body.appendChild(script);
})();
