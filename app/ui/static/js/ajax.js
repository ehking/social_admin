(function () {
  const FEEDBACK_ID = 'ajax-feedback';
  const FEEDBACK_TIMEOUT = 6000;
  let feedbackTimer = null;

  function getFeedbackContainer() {
    let container = document.getElementById(FEEDBACK_ID);
    if (!container) {
      container = document.createElement('div');
      container.id = FEEDBACK_ID;
      container.className = 'ajax-feedback';
      container.setAttribute('role', 'status');
      container.setAttribute('aria-live', 'polite');
      container.hidden = true;
      document.body.appendChild(container);
    }
    return container;
  }

  function clearFeedback() {
    const container = getFeedbackContainer();
    container.textContent = '';
    container.className = 'ajax-feedback';
    container.hidden = true;
    if (feedbackTimer) {
      window.clearTimeout(feedbackTimer);
      feedbackTimer = null;
    }
  }

  function showFeedback(kind, message, warning) {
    if (!message) {
      clearFeedback();
      return;
    }
    const container = getFeedbackContainer();
    container.className = `ajax-feedback ajax-feedback--${kind}`;
    const parts = [message];
    if (warning) {
      parts.push(warning);
    }
    container.textContent = parts.join(' ');
    container.hidden = false;
    if (feedbackTimer) {
      window.clearTimeout(feedbackTimer);
    }
    feedbackTimer = window.setTimeout(clearFeedback, FEEDBACK_TIMEOUT);
  }

  function disableSubmitter(submitter, disabled) {
    if (!submitter) {
      return;
    }
    submitter.disabled = disabled;
    if (disabled) {
      submitter.setAttribute('data-ajax-disabled', 'true');
      submitter.setAttribute('aria-busy', 'true');
    } else {
      submitter.removeAttribute('data-ajax-disabled');
      submitter.removeAttribute('aria-busy');
    }
  }

  function shouldHandleAjax(form) {
    if (!(form instanceof HTMLFormElement)) {
      return false;
    }
    if (form.dataset.ajax === 'false') {
      return false;
    }
    return true;
  }

  function buildRequest(form, submitter) {
    const method = (form.getAttribute('method') || 'GET').toUpperCase();
    let url = form.getAttribute('action') || window.location.href;
    const formData = new FormData(form, submitter);

    const options = {
      method,
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        Accept: 'application/json, text/html;q=0.9, */*;q=0.8',
      },
    };

    if (method === 'GET') {
      const query = new URLSearchParams(formData);
      const queryString = query.toString();
      if (queryString) {
        url += (url.includes('?') ? '&' : '?') + queryString;
      }
    } else {
      options.body = formData;
    }

    return { url, options };
  }

  function dispatchEvent(target, name, detail) {
    const event = new CustomEvent(name, {
      bubbles: true,
      cancelable: true,
      detail,
    });
    return target.dispatchEvent(event);
  }

  function handleRedirect(payload) {
    if (!payload) {
      return;
    }
    const destination = payload.redirect;
    if (!destination) {
      return;
    }
    if (destination === 'reload') {
      window.location.reload();
    } else {
      window.location.assign(destination);
    }
  }

  async function handleAjaxSubmit(event) {
    const form = event.target;
    if (!shouldHandleAjax(form)) {
      return;
    }

    event.preventDefault();

    const confirmMessage = form.dataset.confirm;
    if (confirmMessage && !window.confirm(confirmMessage)) {
      return;
    }

    const submitter = event.submitter instanceof HTMLElement ? event.submitter : form.querySelector('[type="submit"]');

    if (!dispatchEvent(form, 'ajax:before', { form, submitter })) {
      return;
    }

    disableSubmitter(submitter, true);

    const { url, options } = buildRequest(form, submitter);

    try {
      const response = await fetch(url, options);
      const contentType = response.headers.get('content-type') || '';

      if (contentType.includes('application/json')) {
        let payload = null;
        try {
          payload = await response.json();
        } catch (error) {
          const detail = { form, submitter, response, error, handled: false };
          dispatchEvent(form, 'ajax:error', detail);
          if (!detail.handled && !form.dataset.ajaxSilent) {
            showFeedback('error', 'پاسخ نامعتبر از سرور دریافت شد.');
          }
          return;
        }

        const success = response.ok && (!Object.prototype.hasOwnProperty.call(payload, 'success') || payload.success !== false);
        const warning = payload && payload.warning ? payload.warning : undefined;

        if (success) {
          const detail = { form, submitter, response, payload, handled: false };
          dispatchEvent(form, 'ajax:success', detail);
          if (!detail.handled) {
            if (!form.dataset.ajaxSilent) {
              const message = payload && payload.message ? payload.message : 'عملیات با موفقیت انجام شد.';
              showFeedback('success', message, warning);
            }
            handleRedirect(payload);
          }
        } else {
          const message = payload && (payload.error || payload.message)
            ? payload.error || payload.message
            : 'اجرای عملیات با خطا مواجه شد.';
          const detail = { form, submitter, response, payload, message, handled: false };
          dispatchEvent(form, 'ajax:error', detail);
          if (!detail.handled && !form.dataset.ajaxSilent) {
            showFeedback('error', message, warning);
          }
          handleRedirect(payload);
        }
        return;
      }

      if (contentType.includes('text/html')) {
        const html = await response.text();
        const detail = { form, submitter, response, html, handled: false };
        dispatchEvent(form, 'ajax:html', detail);
        if (!detail.handled) {
          document.open();
          document.write(html);
          document.close();
        }
        return;
      }

      const fallbackText = await response.text();
      const message = fallbackText || 'پاسخ نامعتبر از سرور دریافت شد.';
      const detail = { form, submitter, response, message, handled: false };
      dispatchEvent(form, 'ajax:error', detail);
      if (!detail.handled && !form.dataset.ajaxSilent) {
        showFeedback('error', message);
      }
    } catch (error) {
      const detail = { form, submitter, error, handled: false };
      dispatchEvent(form, 'ajax:failure', detail);
      if (!detail.handled && !form.dataset.ajaxSilent) {
        showFeedback('error', 'ارتباط با سرور برقرار نشد.');
      }
    } finally {
      disableSubmitter(submitter, false);
      dispatchEvent(form, 'ajax:complete', { form, submitter });
    }
  }

  document.addEventListener('submit', handleAjaxSubmit, true);
})();
