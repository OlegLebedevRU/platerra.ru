(() => {
  document.documentElement.classList.add('js');
  document.querySelectorAll('.project-images, .prototype-media').forEach(details => {
    details.addEventListener('toggle', () => {
      if (!details.open) return;
      details.querySelectorAll('img[data-src]').forEach(img => {
        img.src = img.dataset.src;
        delete img.dataset.src;
      });
    });
  });
  const filters = document.querySelectorAll('[data-project-filter]');
  const projectRows = document.querySelectorAll('[data-project-category]');
  filters.forEach(button => button.addEventListener('click', () => {
    const selected = button.dataset.projectFilter;
    filters.forEach(filter => filter.setAttribute('aria-pressed', String(filter === button)));
    let visible = 0;
    projectRows.forEach(row => {
      row.hidden = selected !== 'all' && row.dataset.projectCategory !== selected;
      if (!row.hidden) visible += 1;
    });
    const status = document.querySelector('.project-status');
    if (status) status.textContent = `Показано проектов: ${visible}`;
  }));
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.querySelector('#navigation');
  const closeMenu = () => {
    nav?.classList.remove('is-open');
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.setAttribute('aria-label', 'Открыть меню');
  };
  toggle?.addEventListener('click', () => {
    const open = nav.classList.toggle('is-open');
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
  });
  nav?.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMenu));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && nav?.classList.contains('is-open')) {
      closeMenu(); toggle.focus();
    }
  });
  const dialog = document.querySelector('.image-dialog');
  let trigger;
  if (dialog && typeof dialog.showModal === 'function') {
    document.querySelectorAll('[data-image]').forEach(a => a.addEventListener('click', e => {
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button !== 0) return;
      e.preventDefault(); trigger = a;
      const img = dialog.querySelector('img');
      img.src = a.href; img.alt = a.dataset.caption;
      dialog.querySelector('p').textContent = a.dataset.caption;
      dialog.showModal(); document.body.style.overflow = 'hidden';
    }));
    dialog.querySelector('.dialog-close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', e => { if (e.target === dialog) { const r = dialog.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close(); } });
    dialog.addEventListener('close', () => { document.body.style.overflow = ''; trigger?.focus(); });
  }
  const form = document.querySelector('.contact-form');
  const select = document.querySelector('#project-topic');
  if (select) {
    const topic = new URLSearchParams(location.search).get('topic');
    if (['general','l4desk','leo4','terminal','architecture'].includes(topic)) select.value = topic;
  }
  const sendButton = document.querySelector('#send-message');
  const status = document.querySelector('#form-status');
  if (form && sendButton && status) {
    let requestId = crypto.randomUUID();
    let submitted = false;
    let loadingCaptcha = false;
    const loadCaptcha = () => {
      if (loadingCaptcha) return;
      loadingCaptcha = true;
      const script = document.createElement("script");
      script.src = "https://smartcaptcha.yandexcloud.net/captcha.js";
      script.defer = true;
      script.onerror = () => {
        status.textContent = "CAPTCHA не загрузилась. Обновите страницу или напишите нам по email.";
      };
      document.head.append(script);
    };
    if ("IntersectionObserver" in window) {
      const captchaObserver = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          loadCaptcha();
          captchaObserver.disconnect();
        }
      }, { rootMargin: "400px" });
      captchaObserver.observe(form);
    } else {
      loadCaptcha();
    }
    form.addEventListener("focusin", loadCaptcha, { once: true });
    form.addEventListener("input", () => {
      if (!submitted) requestId = crypto.randomUUID();
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submitted || sendButton.disabled || !form.reportValidity()) return;
      const values = new FormData(form);
      const token = window.smartCaptcha?.getResponse() || values.get("smart-token");
      if (!token) {
        loadCaptcha();
        status.textContent = "Пройдите проверку CAPTCHA перед отправкой.";
        return;
      }
      sendButton.disabled = true;
      form.setAttribute("aria-busy", "true");
      status.textContent = "Отправляем обращение…";
      try {
        const response = await fetch(form.action, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: values.get("name"), email: values.get("email"), message: values.get("message"),
            topic: values.get("topic"),
            consent: values.get("consent") === "on", "smart-token": token, request_id: requestId,
          }),
          signal: AbortSignal.timeout(45000),
        });
        const result = await response.json();
        status.textContent = result.message || "Не удалось отправить обращение. Попробуйте позже.";
        if (response.ok && result.ok) {
          submitted = true;
          sendButton.textContent = "Обращение отправлено";
          form.querySelectorAll("input, textarea, select").forEach((field) => { field.disabled = true; });
        }
      } catch {
        status.textContent = "Не удалось получить подтверждение отправки. Проверьте почту перед повтором: обращение могло быть принято.";
      } finally {
        form.removeAttribute("aria-busy");
        if (!submitted) {
          sendButton.disabled = false;
          window.smartCaptcha?.reset();
        }
      }
    });
  }
})();
