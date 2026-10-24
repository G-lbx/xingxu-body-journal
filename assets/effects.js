/* Local, disposable decoration: no storage, network requests, or data changes. */
(() => {
  'use strict';

  function initializeEffects() {
    const body = document.body;
    if (!body || body.dataset.effectsReady === 'true') return;
    body.dataset.effectsReady = 'true';

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
    const toggle = document.getElementById('effects-toggle');
    const label = document.getElementById('effects-label');
    let requestedEnabled = body.dataset.effects !== 'off' && !reducedMotion.matches;
    let enabled = false;
    let frame = 0;
    let previousTime = 0;
    let pointerVisible = false;
    let targetX = 0;
    let targetY = 0;
    let currentX = 0;
    let currentY = 0;
    let activePanel = null;
    let panelBounds = null;
    let panelDirty = false;
    let arrivalTimer;
    let messageTimer;
    const ripples = new Map();

    function decoration(className, parent) {
      const element = document.createElement('span');
      element.className = className;
      element.setAttribute('aria-hidden', 'true');
      parent.append(element);
      return element;
    }

    const cursor = decoration('fx-cursor', body);
    decoration('fx-cursor-aura', cursor);
    decoration('fx-cursor-ring', cursor);

    document.querySelectorAll('.card, .metric, .task').forEach(panel => {
      panel.classList.add('fx-panel');
      // Append at the end so a details element retains its original first summary.
      decoration('panel-spotlight', panel);
    });
    document.querySelectorAll('.btn').forEach(button => {
      button.classList.add('fx-button');
      decoration('button-sheen', button);
    });
    const hero = document.querySelector('.hero-panel .hero-visual');
    if (hero) {
      decoration('hero-scanline', hero);
      decoration('hero-reactor-glow', hero);
    }

    const message = document.createElement('div');
    message.className = 'effects-message';
    message.setAttribute('role', 'status');
    message.setAttribute('aria-live', 'polite');
    message.setAttribute('aria-atomic', 'true');
    body.append(message);

    function announce(text) {
      window.clearTimeout(messageTimer);
      message.textContent = text;
      messageTimer = window.setTimeout(() => { message.textContent = ''; }, 3400);
    }

    function removeRipple(ripple) {
      window.clearTimeout(ripples.get(ripple));
      ripples.delete(ripple);
      ripple.remove();
    }

    function stopPointer() {
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
      previousTime = 0;
      pointerVisible = false;
      cursor.classList.remove('is-visible', 'is-interactive');
      if (activePanel) activePanel.classList.remove('is-lit');
      activePanel = null;
      panelBounds = null;
      panelDirty = false;
    }

    function canTrackPointer() {
      return enabled && finePointer.matches && !document.hidden;
    }

    // Only one RAF is used. It stops as soon as the follower reaches the pointer.
    function renderPointer(time) {
      frame = 0;
      if (!canTrackPointer() || !pointerVisible) return;
      const elapsed = previousTime ? Math.min(time - previousTime, 48) : 16;
      previousTime = time;
      const smoothing = 1 - Math.exp(-elapsed / 38);
      currentX += (targetX - currentX) * smoothing;
      currentY += (targetY - currentY) * smoothing;
      const settling = Math.abs(targetX - currentX) + Math.abs(targetY - currentY) > .12;
      if (!settling) {
        currentX = targetX;
        currentY = targetY;
      }
      cursor.style.transform = `translate3d(${currentX.toFixed(2)}px, ${currentY.toFixed(2)}px, 0)`;
      if (panelDirty && activePanel && panelBounds) {
        activePanel.style.setProperty('--spot-x', `${(targetX - panelBounds.left).toFixed(1)}px`);
        activePanel.style.setProperty('--spot-y', `${(targetY - panelBounds.top).toFixed(1)}px`);
        panelDirty = false;
      }
      if (settling) frame = window.requestAnimationFrame(renderPointer);
      else previousTime = 0;
    }

    function requestPointerFrame() {
      if (!frame && canTrackPointer()) frame = window.requestAnimationFrame(renderPointer);
    }

    function updateState() {
      enabled = requestedEnabled && !reducedMotion.matches;
      body.dataset.effects = enabled ? 'on' : 'off';
      body.classList.toggle('effects-paused', document.hidden);
      if (toggle) {
        toggle.setAttribute('aria-pressed', String(enabled));
        toggle.setAttribute('aria-disabled', String(reducedMotion.matches));
        toggle.title = reducedMotion.matches
          ? '已遵循系统的减少动态效果设置，动态特效保持关闭'
          : enabled ? '关闭动态特效，仅在当前页面生效' : '开启动态特效，仅在当前页面生效';
        toggle.setAttribute('aria-label', reducedMotion.matches
          ? '动态特效已关闭，遵循系统减少动态效果设置'
          : enabled ? '动态特效已开启，点击关闭' : '动态特效已关闭，点击开启');
      }
      if (label) label.textContent = reducedMotion.matches ? '减少动态已开启' : enabled ? '特效开启' : '特效关闭';
      if (!enabled || document.hidden) {
        stopPointer();
        [...ripples.keys()].forEach(removeRipple);
      }
      if (!enabled) {
        window.clearTimeout(arrivalTimer);
        body.classList.remove('effects-arriving');
      }
    }

    document.addEventListener('pointermove', event => {
      if (!canTrackPointer() || event.pointerType === 'touch') return;
      const target = event.target instanceof Element ? event.target : null;
      if (!target) return;
      targetX = event.clientX;
      targetY = event.clientY;
      if (!pointerVisible) {
        currentX = targetX;
        currentY = targetY;
        pointerVisible = true;
        cursor.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
        cursor.classList.add('is-visible');
      }
      const interactive = target.closest('button, a[href], summary, input, select, textarea, [role="button"]');
      cursor.classList.toggle('is-interactive', Boolean(interactive && !interactive.matches(':disabled, [aria-disabled="true"]')));
      const panel = target.closest('.fx-panel');
      if (panel !== activePanel) {
        if (activePanel) activePanel.classList.remove('is-lit');
        activePanel = panel;
        panelBounds = panel ? panel.getBoundingClientRect() : null;
        if (panel) panel.classList.add('is-lit');
      }
      panelDirty = Boolean(activePanel);
      requestPointerFrame();
    }, { passive: true });

    document.documentElement.addEventListener('pointerleave', stopPointer, { passive: true });
    document.addEventListener('pointercancel', stopPointer, { passive: true });
    document.addEventListener('keydown', event => {
      if (event.key === 'Tab') stopPointer();
    });
    window.addEventListener('blur', stopPointer);
    window.addEventListener('resize', stopPointer, { passive: true });
    document.addEventListener('scroll', stopPointer, { passive: true, capture: true });

    document.addEventListener('click', event => {
      if (!enabled || document.hidden || !(event.target instanceof Element)) return;
      const button = event.target.closest('.btn');
      if (!button || button.matches(':disabled, [aria-disabled="true"]')) return;
      const bounds = button.getBoundingClientRect();
      const size = Math.max(bounds.width, bounds.height) * 2;
      const x = event.detail === 0 ? bounds.width / 2 : event.clientX - bounds.left;
      const y = event.detail === 0 ? bounds.height / 2 : event.clientY - bounds.top;
      // Repeated clicks can never accumulate an unbounded decoration list.
      button.querySelectorAll('.button-ripple').forEach(removeRipple);
      if (ripples.size >= 5) removeRipple(ripples.keys().next().value);
      const ripple = decoration('button-ripple', button);
      ripple.style.width = `${size}px`;
      ripple.style.height = `${size}px`;
      ripple.style.left = `${x}px`;
      ripple.style.top = `${y}px`;
      ripple.addEventListener('animationend', () => removeRipple(ripple), { once: true });
      ripples.set(ripple, window.setTimeout(() => removeRipple(ripple), 800));
    });

    if (toggle) toggle.addEventListener('click', () => {
      if (reducedMotion.matches) {
        announce('已遵循系统的“减少动态效果”设置，动态特效保持关闭。');
        return;
      }
      requestedEnabled = !enabled;
      updateState();
      announce(enabled ? '动态特效已开启，仅在当前页面生效。' : '动态特效已关闭，所有数据仍正常显示。');
    });

    reducedMotion.addEventListener('change', () => {
      // A request to reduce motion always wins; clearing it does not auto-enable.
      if (reducedMotion.matches) requestedEnabled = false;
      updateState();
    });
    finePointer.addEventListener('change', stopPointer);
    document.addEventListener('visibilitychange', updateState);

    updateState();
    if (enabled && !document.hidden) {
      body.classList.add('effects-arriving');
      arrivalTimer = window.setTimeout(() => body.classList.remove('effects-arriving'), 1000);
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initializeEffects, { once: true });
  else initializeEffects();
})();
