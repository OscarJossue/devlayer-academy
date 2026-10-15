(() => {
  const body = document.body;
  const openButton = document.querySelector('[data-sidebar-toggle]');
  const collapseButton = document.querySelector('[data-sidebar-collapse]');
  const overlay = document.querySelector('[data-sidebar-overlay]');
  const storageKey = 'devlayer-sidebar-collapsed';

  const closeMobile = () => body.classList.remove('sidebar-open');

  if (openButton) openButton.addEventListener('click', () => body.classList.toggle('sidebar-open'));
  if (overlay) overlay.addEventListener('click', closeMobile);

  if (collapseButton) {
    if (localStorage.getItem(storageKey) === '1' && window.innerWidth > 900) body.classList.add('sidebar-collapsed');
    collapseButton.addEventListener('click', () => {
      body.classList.toggle('sidebar-collapsed');
      localStorage.setItem(storageKey, body.classList.contains('sidebar-collapsed') ? '1' : '0');
    });
  }

  const currentPath = window.location.pathname;
  document.querySelectorAll('.sidebar-link').forEach((link) => {
    if (link.tagName !== 'A') return;
    link.addEventListener('click', closeMobile);
    try {
      const path = new URL(link.href, window.location.origin).pathname;
      if (path !== '/' && (currentPath === path || currentPath.startsWith(path))) link.classList.add('is-active');
    } catch (_) {}
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 900) closeMobile();
  });
})();
