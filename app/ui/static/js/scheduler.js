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

  function matchesSchedulerForm(form) {
    if (!(form instanceof HTMLFormElement)) {
      return false;
    }
    const action = form.getAttribute('action') || '';
    return action.endsWith('/scheduler') || action.endsWith('/scheduler/delete');
  }

  document.addEventListener(
    'ajax:success',
    (event) => {
      const form = event.target;
      if (!matchesSchedulerForm(form)) {
        return;
      }

      const detail = event.detail || {};
      const payload = detail.payload || {};

      if (Array.isArray(payload.posts)) {
        renderPosts(payload.posts);
      }

      const warning = payload.warning ? payload.warning : undefined;
      const message = payload.message || 'عملیات با موفقیت انجام شد.';
      showFeedback('success', message, warning);

      if ((form.getAttribute('action') || '').endsWith('/scheduler')) {
        form.reset();
      }

      detail.handled = true;
    },
    true,
  );

  document.addEventListener(
    'ajax:error',
    (event) => {
      const form = event.target;
      if (!matchesSchedulerForm(form)) {
        return;
      }

      const detail = event.detail || {};
      const payload = detail.payload || {};
      const warning = payload.warning ? payload.warning : undefined;
      const message = detail.message || payload.error || 'اجرای عملیات با خطا مواجه شد.';
      showFeedback('error', message, warning);
      detail.handled = true;
    },
    true,
  );
})();
