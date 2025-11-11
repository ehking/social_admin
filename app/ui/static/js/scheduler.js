(function () {
  const postsContainer = document.getElementById('scheduled-posts-container');
  const feedbackElement = document.getElementById('scheduler-feedback');

  if (!postsContainer) {
    return;
  }

  function showFeedback(kind, message, warning) {
    if (!feedbackElement) {
      return;
    }
    if (!message) {
      feedbackElement.hidden = true;
      feedbackElement.textContent = '';
      feedbackElement.className = 'alert';
      return;
    }

    const classMap = {
      success: 'alert alert-success',
      error: 'alert alert-error',
      warning: 'alert alert-warning',
      info: 'alert alert-info',
    };
    feedbackElement.className = classMap[kind] || classMap.info;
    const parts = [message];
    if (warning) {
      parts.push(warning);
    }
    feedbackElement.textContent = parts.join(' ');
    feedbackElement.hidden = false;
  }

  function buildCell(tag, text, className) {
    const cell = document.createElement(tag);
    if (className) {
      cell.className = className;
    }
    if (text) {
      cell.textContent = text;
    }
    return cell;
  }

  function renderPosts(posts) {
    postsContainer.innerHTML = '';
    if (!Array.isArray(posts) || posts.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = 'هیچ زمان‌بندی فعالی ثبت نشده است.';
      postsContainer.appendChild(empty);
      return;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'table-wrapper';

    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    ['عنوان', 'حساب', 'زمان اجرا', 'وضعیت', 'لینک ویدیو', ''].forEach((header) => {
      headRow.appendChild(buildCell('th', header));
    });
    thead.appendChild(headRow);

    const tbody = document.createElement('tbody');

    posts.forEach((post) => {
      const row = document.createElement('tr');
      row.dataset.video = post.video_url || '';
      row.dataset.content = post.content || '';

      const titleCell = buildCell('td', post.title || '');
      const accountCell = buildCell('td', post.account || '-');
      const timeCell = buildCell('td', post.scheduled_time_display || '');

      const statusCell = document.createElement('td');
      const statusBadge = document.createElement('span');
      statusBadge.className = 'badge badge-secondary';
      statusBadge.textContent = post.status || 'pending';
      statusCell.appendChild(statusBadge);

      const videoCell = document.createElement('td');
      if (post.video_url) {
        const link = document.createElement('a');
        link.href = post.video_url;
        link.target = '_blank';
        link.rel = 'noopener';
        link.className = 'link';
        link.textContent = 'مشاهده';
        videoCell.appendChild(link);
      } else {
        videoCell.textContent = '-';
      }

      const actionCell = buildCell('td', null, 'actions');
      const deleteForm = document.createElement('form');
      deleteForm.method = 'post';
      deleteForm.action = '/scheduler/delete';
      deleteForm.dataset.ajax = 'true';
      deleteForm.dataset.confirm = 'زمان‌بندی حذف شود؟';

      const hiddenInput = document.createElement('input');
      hiddenInput.type = 'hidden';
      hiddenInput.name = 'post_id';
      hiddenInput.value = String(post.id);

      const deleteButton = document.createElement('button');
      deleteButton.type = 'submit';
      deleteButton.className = 'btn btn-small btn-danger';
      deleteButton.textContent = 'حذف';

      deleteForm.appendChild(hiddenInput);
      deleteForm.appendChild(deleteButton);
      actionCell.appendChild(deleteForm);

      row.appendChild(titleCell);
      row.appendChild(accountCell);
      row.appendChild(timeCell);
      row.appendChild(statusCell);
      row.appendChild(videoCell);
      row.appendChild(actionCell);

      tbody.appendChild(row);
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    wrapper.appendChild(table);
    postsContainer.appendChild(wrapper);
  }

  async function handleAjaxSubmit(event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.dataset.ajax !== 'true') {
      return;
    }

    event.preventDefault();

    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      return;
    }

    const submitButton = form.querySelector('button[type="submit"]');
    if (submitButton) {
      submitButton.disabled = true;
    }

    try {
      const formData = new FormData(form);
      const response = await fetch(form.action, {
        method: (form.method || 'post').toUpperCase(),
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
        },
      });

      let payload = null;
      try {
        payload = await response.json();
      } catch (error) {
        showFeedback('error', 'پاسخ نامعتبر از سرور دریافت شد.');
        return;
      }

      if (!response.ok || !payload || payload.success === false) {
        const message = payload && payload.error ? payload.error : 'اجرای عملیات با خطا مواجه شد.';
        const warning = payload && payload.warning ? payload.warning : undefined;
        showFeedback('error', message, warning);
      } else {
        const warning = payload.warning ? payload.warning : undefined;
        showFeedback('success', payload.message || 'عملیات با موفقیت انجام شد.', warning);
        if (form.action.endsWith('/scheduler')) {
          form.reset();
        }
      }

      if (payload && Array.isArray(payload.posts)) {
        renderPosts(payload.posts);
      }
    } catch (error) {
      showFeedback('error', 'ارتباط با سرور برقرار نشد.');
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
      }
    }
  }

  document.addEventListener('submit', handleAjaxSubmit, true);
})();
