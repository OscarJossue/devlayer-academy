(() => {
  'use strict';

  const protectedSelector = '[data-protected-media]';
  const insideProtected = (target) => target instanceof Element && Boolean(target.closest(protectedSelector));
  const hasProtectedContent = () => Boolean(document.querySelector(protectedSelector));
  const isWindows = /Windows/i.test(navigator.userAgent || '') || /^Win/i.test(navigator.platform || '');
  const isMac = /Mac/i.test(navigator.platform || '');

  let guardTimer = null;
  let guardActive = false;
  let capturePrearmed = false;
  let metaDown = false;
  let shiftDown = false;

  function clearLegacyStates() {
    document.body.classList.remove(
      'protected-capture-shield',
      'media-external-focus-guard',
      'pdf-external-capture-guard'
    );
  }

  function setGuard(active) {
    guardActive = Boolean(active) && hasProtectedContent();
    document.body.classList.toggle('media-capture-guard', guardActive);
  }

  function cancelGuardTimer() {
    window.clearTimeout(guardTimer);
    guardTimer = null;
  }

  function holdGuard() {
    if (!hasProtectedContent()) return;
    cancelGuardTimer();
    setGuard(true);
  }

  function releaseGuard(delay = 120) {
    cancelGuardTimer();
    guardTimer = window.setTimeout(() => {
      if (capturePrearmed || metaDown || shiftDown && metaDown) return;
      setGuard(false);
    }, Math.max(0, delay));
  }

  function pulseGuard(duration = 1500) {
    if (!hasProtectedContent()) return;
    holdGuard();
    guardTimer = window.setTimeout(() => {
      if (!capturePrearmed) setGuard(false);
    }, duration);
  }

  function armProtectedRegions() {
    clearLegacyStates();
    document.querySelectorAll(protectedSelector).forEach((node) => {
      node.dataset.securityArmed = 'true';
      node.classList.add('security-armed');
    });
  }

  function beginCapturePrearm() {
    if (!hasProtectedContent()) return;
    capturePrearmed = true;
    holdGuard();
  }

  function endCapturePrearm(delay = 900) {
    capturePrearmed = false;
    releaseGuard(delay);
  }

  function isPrintScreen(key) {
    return key === 'printscreen' || key === 'snapshot';
  }

  function handleKeyDown(event) {
    if (!hasProtectedContent()) return;

    const key = String(event.key || '').toLowerCase();
    const modifier = event.ctrlKey || event.metaKey;

    if (key === 'meta') metaDown = true;
    if (key === 'shift') shiftDown = true;

    // Pre-arm before Windows Snipping Tool receives the final "S".
    // This is intentionally limited to Windows-key + Shift, so normal clicks,
    // video controls, PDF navigation and ordinary focus changes are untouched.
    if (isWindows && metaDown && shiftDown) {
      beginCapturePrearm();
    }

    // macOS screenshots: Cmd+Shift+3/4/5. Pre-arm while Cmd+Shift is held.
    if (isMac && metaDown && shiftDown) {
      beginCapturePrearm();
    }

    const printScreen = isPrintScreen(key);
    const winSnip = isWindows && metaDown && shiftDown && key === 's';
    const macCapture = isMac && metaDown && shiftDown && ['3', '4', '5'].includes(key);
    const browserCapture = event.ctrlKey && event.shiftKey && key === 's';
    const printOrSave = modifier && ['p', 's'].includes(key) && !winSnip;
    const sourceShortcut = modifier && key === 'u';

    if (printScreen || winSnip || macCapture || browserCapture) {
      beginCapturePrearm();
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
      return;
    }

    if (printOrSave || sourceShortcut) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
    }
  }

  function handleKeyUp(event) {
    const key = String(event.key || '').toLowerCase();

    if (isPrintScreen(key)) {
      pulseGuard(1600);
      event.preventDefault();
      return;
    }

    if (key === 'meta') metaDown = false;
    if (key === 'shift') shiftDown = false;

    if (!metaDown || !shiftDown) {
      // Keep the protected pixels covered long enough for the OS capture UI
      // to take focus. If no capture UI opens, the mask disappears quickly.
      endCapturePrearm(1100);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', armProtectedRegions, { once: true });
  } else {
    armProtectedRegions();
  }
  window.addEventListener('load', armProtectedRegions, { once: true });
  window.addEventListener('pageshow', () => {
    capturePrearmed = false;
    metaDown = false;
    shiftDown = false;
    setGuard(false);
    armProtectedRegions();
  });

  document.addEventListener('load', (event) => {
    const target = event.target;
    if (target instanceof HTMLImageElement && target.matches('[data-pdf-page]')) armProtectedRegions();
  }, true);

  const observer = new MutationObserver(() => {
    if (hasProtectedContent()) armProtectedRegions();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  document.addEventListener('contextmenu', (event) => {
    if (insideProtected(event.target)) event.preventDefault();
  }, true);
  document.addEventListener('dragstart', (event) => {
    if (insideProtected(event.target)) event.preventDefault();
  }, true);
  document.addEventListener('selectstart', (event) => {
    if (insideProtected(event.target)) event.preventDefault();
  }, true);
  document.addEventListener('copy', (event) => {
    if (insideProtected(event.target)) event.preventDefault();
  }, true);
  document.addEventListener('cut', (event) => {
    if (insideProtected(event.target)) event.preventDefault();
  }, true);

  // Capture phase on both objects: whichever owns keyboard focus gets the
  // first chance to cover the protected pixels.
  window.addEventListener('keydown', handleKeyDown, true);
  document.addEventListener('keydown', handleKeyDown, true);
  window.addEventListener('keyup', handleKeyUp, true);
  document.addEventListener('keyup', handleKeyUp, true);

  // The secure-video iframe sends this message when keyboard focus is inside
  // the player. This lets the parent cover PDF + video together, fixing the
  // previous small-view case where only the iframe knew about PrintScreen.
  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin || !event.data || event.data.source !== 'academy-secure-video') return;
    if (event.data.type === 'capture-prearm') {
      capturePrearmed = true;
      holdGuard();
    } else if (event.data.type === 'capture-pulse') {
      pulseGuard(Number(event.data.duration) || 1600);
    } else if (event.data.type === 'capture-release') {
      capturePrearmed = false;
      releaseGuard(Number(event.data.delay) || 900);
    }
  }, true);

  // Never activate protection merely because focus changed. We only retain an
  // already-armed guard if the OS takes focus after a capture shortcut.
  window.addEventListener('blur', () => {
    if (capturePrearmed || guardActive) holdGuard();
  }, true);
  window.addEventListener('focus', () => {
    metaDown = false;
    shiftDown = false;
    capturePrearmed = false;
    releaseGuard(80);
  }, true);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && capturePrearmed) holdGuard();
    if (!document.hidden) {
      capturePrearmed = false;
      releaseGuard(80);
    }
  }, true);

  // Prevent screen capture initiated from page JavaScript. This cannot block
  // an external camera or guarantee interception of every OS-level screenshot.
  try {
    if (navigator.mediaDevices && typeof navigator.mediaDevices.getDisplayMedia === 'function') {
      navigator.mediaDevices.getDisplayMedia = () => Promise.reject(
        new DOMException('Captura de pantalla deshabilitada por Academy.', 'NotAllowedError')
      );
    }
  } catch (_) {}
})();
