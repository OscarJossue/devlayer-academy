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

// Promociones de cursos: simplifica el formulario y muestra el precio final antes de guardar.
(function setupCourseDiscountForms(){
  function init(){
    const enabled = document.getElementById('id_discount_enabled');
    if(!enabled || enabled.dataset.discountReady === '1') return;
    enabled.dataset.discountReady = '1';
    const type = document.getElementById('id_discount_type');
    const value = document.getElementById('id_discount_value');
    const start = document.getElementById('id_discount_starts_at');
    const end = document.getElementById('id_discount_ends_at');
    const price = document.getElementById('id_price');
    if(!type || !value || !price) return;

    const field = value.closest('.form-field') || value.parentElement;
    const preview = document.createElement('div');
    preview.className = 'discount-live-preview';
    preview.setAttribute('aria-live','polite');
    if(field) field.appendChild(preview);

    function money(n){ return Number(n || 0).toFixed(2); }
    function refresh(){
      const on = !!enabled.checked;
      [type,value,start,end].filter(Boolean).forEach(el => { el.setAttribute('aria-disabled', on ? 'false' : 'true'); });
      if(!on){ preview.classList.remove('is-visible'); preview.innerHTML=''; return; }
      const base = Math.max(0, parseFloat(price.value || '0') || 0);
      const raw = Math.max(0, parseFloat(value.value || '0') || 0);
      let final = base;
      let label = '';
      if(type.value === 'FIXED'){
        final = Math.max(0, base - raw);
        label = 'Ahorra ' + money(Math.min(raw, base));
      }else{
        const pct = Math.min(raw,100);
        final = Math.max(0, base - (base * pct / 100));
        label = '-' + (Number.isInteger(pct) ? pct : pct.toFixed(2)) + '%';
      }
      preview.innerHTML = '<span class="offer-chip">Oferta</span><del>$'+money(base)+'</del><strong>$'+money(final)+'</strong><span>'+label+'</span>';
      preview.classList.add('is-visible');
    }
    [enabled,type,value,price,start,end].filter(Boolean).forEach(el => el.addEventListener('input', refresh));
    [enabled,type].forEach(el => el && el.addEventListener('change', refresh));
    refresh();
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();

// Tipos de acceso del curso: muestra exclusivamente la configuración aplicable.
(function setupCourseAccessFields(){
  function init(){
    const accessType = document.getElementById('id_access_type');
    if(!accessType || accessType.dataset.accessUiReady === '1') return;
    accessType.dataset.accessUiReady = '1';

    const accessDays = document.getElementById('id_access_days');
    const fixedUntil = document.getElementById('id_access_fixed_until');
    const postPolicy = document.getElementById('id_post_certificate_policy');
    const postDays = document.getElementById('id_post_certificate_days');

    const wrapper = (el) => el ? el.closest('.form-field') : null;
    const setVisible = (el, visible) => {
      if(!el) return;
      const box = wrapper(el);
      if(box) box.classList.toggle('course-access-field-hidden', !visible);
      el.disabled = !visible;
      el.setAttribute('aria-hidden', visible ? 'false' : 'true');
    };

    let summary = accessType.closest('.form-field')?.querySelector('.course-access-live-summary');
    if(!summary){
      summary = document.createElement('div');
      summary.className = 'course-access-live-summary';
      summary.setAttribute('aria-live', 'polite');
      accessType.closest('.form-field')?.appendChild(summary);
    }

    function refresh(){
      const type = accessType.value;
      const untilCertificate = type === 'UNTIL_CERTIFICATE';
      setVisible(accessDays, type === 'DAYS');
      setVisible(fixedUntil, type === 'FIXED_DATE');
      setVisible(postPolicy, untilCertificate);
      setVisible(postDays, untilCertificate && !!postPolicy && postPolicy.value === 'DAYS');

      let text = '';
      if(type === 'PERMANENT') text = 'Acceso permanente · sin vencimiento.';
      else if(type === 'DAYS') text = 'El estudiante tendrá acceso durante la cantidad de días indicada desde que se active su matrícula.';
      else if(type === 'FIXED_DATE') text = 'Todos los estudiantes tendrán acceso únicamente hasta la fecha y hora seleccionadas.';
      else if(type === 'UNTIL_CERTIFICATE') {
        if(postPolicy?.value === 'KEEP') text = 'El acceso continúa de forma permanente después de obtener el certificado.';
        else if(postPolicy?.value === 'DAYS') text = 'Al certificarse, el estudiante conservará acceso durante los días adicionales indicados.';
        else text = 'El acceso finalizará cuando el estudiante obtenga su certificado.';
      }
      if(summary) summary.textContent = text;
    }

    accessType.addEventListener('change', refresh);
    if(postPolicy) postPolicy.addEventListener('change', refresh);
    refresh();
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
