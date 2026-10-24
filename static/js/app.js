(() => {
  const body = document.body;
  const openButton = document.querySelector('[data-sidebar-toggle]');
  const collapseButton = document.querySelector('[data-sidebar-collapse]');
  const overlay = document.querySelector('[data-sidebar-overlay]');
  const storageKey = 'devlayer-sidebar-collapsed';

  const closeMobile = () => body.classList.remove('sidebar-open');

  const syncCollapseButton = () => {
    if (!collapseButton) return;
    const collapsed = body.classList.contains('sidebar-collapsed');
    const label = collapsed ? 'Expandir menú' : 'Contraer menú';
    collapseButton.setAttribute('aria-label', label);
    collapseButton.setAttribute('title', label);
    collapseButton.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  };

  if (openButton) openButton.addEventListener('click', () => body.classList.toggle('sidebar-open'));
  if (overlay) overlay.addEventListener('click', closeMobile);

  if (collapseButton) {
    if (localStorage.getItem(storageKey) === '1' && window.innerWidth > 900) {
      body.classList.add('sidebar-collapsed');
    }
    syncCollapseButton();
    collapseButton.addEventListener('click', () => {
      body.classList.toggle('sidebar-collapsed');
      localStorage.setItem(storageKey, body.classList.contains('sidebar-collapsed') ? '1' : '0');
      syncCollapseButton();
    });
  }

  // Si el navegador intenta restaurar un panel privado desde BFCache después
  // de cerrar sesión, recargamos para que Django vuelva a validar autenticación.
  window.addEventListener('pageshow', (event) => {
    if (event.persisted && body.classList.contains('con-panel')) {
      window.location.reload();
    }
  });

  const sidebarLinks = [...document.querySelectorAll('.sidebar-link')];
  sidebarLinks.forEach((link) => {
    if (link.tagName === 'A') link.addEventListener('click', closeMobile);
  });

  // El estudiante recibe su sección activa desde Django. Para los demás roles,
  // seleccionamos una sola coincidencia: la ruta más específica, nunca varias.
  if (!document.querySelector('.sidebar-nav .sidebar-link.is-active')) {
    const currentPath = window.location.pathname.replace(/\/+$/, '') || '/';
    const candidates = sidebarLinks
      .filter((link) => link.tagName === 'A')
      .map((link) => {
        try {
          const path = new URL(link.href, window.location.origin).pathname.replace(/\/+$/, '') || '/';
          const matches = path !== '/' && (currentPath === path || currentPath.startsWith(`${path}/`));
          return matches ? { link, path } : null;
        } catch (_) {
          return null;
        }
      })
      .filter(Boolean)
      .sort((a, b) => b.path.length - a.path.length);

    if (candidates.length) candidates[0].link.classList.add('is-active');
  }

  window.addEventListener('resize', () => {
    if (window.innerWidth > 900) closeMobile();
    syncCollapseButton();
  });
})();


// Payment method cards keep the form select synchronized and explain special flows.
(() => {
  const select = document.querySelector('[data-payment-method-select]');
  if (!select) return;
  const cards = [...document.querySelectorAll('[data-payment-choice]')];
  const help = document.querySelector('[data-payment-method-help]');
  const helpText = {
    CARD: 'Para tarjeta, solicita primero el link por WhatsApp. Después puedes registrar aquí la referencia del pago o enviarla directamente por WhatsApp.',
    WHATSAPP: 'El comprobante puede quedar respaldado en el chat de WhatsApp de la academia.',
    PAYPAL: 'Completa el pago en PayPal y adjunta aquí el comprobante o captura legible.',
    PAYPHONE: 'Completa el pago en PayPhone y adjunta aquí el comprobante o captura legible.',
    PAYMENT_LINK: 'Abre el link configurado por la academia, completa el pago y adjunta el comprobante.',
    BANK: 'Realiza la transferencia a una de las cuentas visibles y adjunta el comprobante.',
  };
  const refresh = () => {
    cards.forEach(card => card.classList.toggle('is-selected', card.dataset.paymentChoice === select.value));
    if (help) {
      const text = helpText[select.value] || '';
      help.textContent = text;
      help.classList.toggle('is-visible', Boolean(text));
    }
  };
  cards.forEach(card => card.addEventListener('click', (event) => {
    if (event.target.closest('a,button,input,select')) return;
    const value = card.dataset.paymentChoice;
    if ([...select.options].some(option => option.value === value)) {
      select.value = value;
      select.dispatchEvent(new Event('change', {bubbles:true}));
    }
  }));
  select.addEventListener('change', refresh);
  refresh();
})();


// Owner payment settings: show details only for enabled methods.
(() => {
  const cards = [...document.querySelectorAll('[data-payment-config]')];
  if (!cards.length) return;
  const refreshCard = (card) => {
    const checkbox = card.querySelector('input[type="checkbox"]');
    if (!checkbox) return;
    card.classList.toggle('is-disabled', !checkbox.checked);
  };
  cards.forEach(card => {
    const checkbox = card.querySelector('input[type="checkbox"]');
    if (!checkbox) return;
    checkbox.addEventListener('change', () => refreshCard(card));
    refreshCard(card);
  });
})();
