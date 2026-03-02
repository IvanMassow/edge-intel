/* ==========================================================================
   MAKES NEWS PORTAL — Client-side JavaScript
   Live RSS polling, Fetch Draft / Analyse, Copy RSS, scroll reveals
   ========================================================================== */

(function() {
  'use strict';

  // --- Scroll Reveal ---
  var revealObserver = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('reveal--visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

  document.querySelectorAll('.reveal').forEach(function(el) {
    revealObserver.observe(el);
  });

  // --- Copy RSS to Clipboard ---
  document.querySelectorAll('[data-rss-url]').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      var url = this.getAttribute('data-rss-url');
      if (!url) return;
      navigator.clipboard.writeText(url).then(function() {
        showToast('RSS link copied');
      }).catch(function() {
        // Fallback
        var ta = document.createElement('textarea');
        ta.value = url;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('RSS link copied');
      });
    });
  });

  function showToast(message) {
    var toast = document.getElementById('copy-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'copy-toast';
      toast.className = 'copy-toast';
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('copy-toast--show');
    setTimeout(function() {
      toast.classList.remove('copy-toast--show');
    }, 2000);
  }

  // --- Fetch Draft / Analyse Buttons ---
  document.querySelectorAll('[data-fetch-url]').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      var url = this.getAttribute('data-fetch-url');
      var card = this.closest('.wire-card');
      if (!url) return;

      // Disable all buttons on this card
      if (card) {
        card.querySelectorAll('[data-fetch-url]').forEach(function(b) {
          b.classList.add('btn-action--loading');
          b.disabled = true;
        });
      }

      this.classList.add('btn-action--loading');
      this.disabled = true;

      fetch(url)
        .then(function(response) {
          if (!response.ok) {
            return response.json().then(function(data) {
              if (data.message) showToast(data.message);
              throw new Error('Request failed');
            });
          }
          return response.json();
        })
        .then(function(data) {
          showToast(data.message || 'Queued successfully');
          // Reload after short delay to show updated content
          setTimeout(function() { window.location.reload(); }, 1500);
        })
        .catch(function(error) {
          if (card) {
            card.querySelectorAll('[data-fetch-url]').forEach(function(b) {
              b.classList.remove('btn-action--loading');
              b.disabled = false;
            });
          }
        });
    });
  });

  // --- Live Wire Polling ---
  var wireContainer = document.getElementById('wire-articles');
  var rssUrl = wireContainer ? wireContainer.getAttribute('data-rss-url') : null;
  var seenGuids = new Set();

  // Collect initially rendered GUIDs
  document.querySelectorAll('[data-guid]').forEach(function(el) {
    seenGuids.add(el.getAttribute('data-guid'));
  });

  if (rssUrl && wireContainer) {
    setInterval(pollRSS, 30000); // Every 30 seconds
  }

  function pollRSS() {
    fetch(rssUrl)
      .then(function(r) { return r.text(); })
      .then(function(xml) {
        var parser = new DOMParser();
        var doc = parser.parseFromString(xml, 'text/xml');
        var items = doc.querySelectorAll('item');
        var newItems = [];

        items.forEach(function(item) {
          var guid = item.querySelector('guid');
          if (guid && !seenGuids.has(guid.textContent.trim())) {
            newItems.push(item);
            seenGuids.add(guid.textContent.trim());
          }
        });

        if (newItems.length > 0) {
          updateTimestamp();
          newItems.reverse().forEach(function(item) {
            insertWireCard(item);
          });
        }
      })
      .catch(function() { /* silently fail */ });
  }

  function updateTimestamp() {
    var el = document.getElementById('wire-timestamp');
    if (el) el.textContent = 'Updated: just now';
  }

  function insertWireCard(item) {
    var title = item.querySelector('title');
    var link = item.querySelector('link');
    var guid = item.querySelector('guid');
    var enclosure = item.querySelector('enclosure');
    var desc = item.querySelector('description');

    var titleText = title ? title.textContent.trim() : '';
    var linkHref = link ? link.textContent.trim() : '#';
    var guidText = guid ? guid.textContent.trim() : '';

    // Extract bullets from description
    var bullets = [];
    if (desc && desc.textContent) {
      var tmp = document.createElement('div');
      tmp.innerHTML = desc.textContent;
      var lis = tmp.querySelectorAll('li');
      lis.forEach(function(li, i) {
        if (i < 5) bullets.push(li.textContent.trim());
      });
    }

    var bulletHtml = '';
    if (bullets.length > 0) {
      bulletHtml = '<ul class="wire-card__bullets">';
      bullets.forEach(function(b) {
        bulletHtml += '<li>' + escapeHtml(b) + '</li>';
      });
      bulletHtml += '</ul>';
    }

    var html = '<div class="wire-card wire-card--new" data-guid="' + escapeHtml(guidText) + '">'
      + '<div class="wire-card__header">'
      + '<span class="wire-card__breaking">NEW</span>'
      + '<span class="wire-card__time">just now</span>'
      + '</div>'
      + '<h3 class="wire-card__title"><a href="' + escapeHtml(linkHref) + '">' + escapeHtml(titleText) + '</a></h3>'
      + bulletHtml
      + '</div>';

    wireContainer.insertAdjacentHTML('afterbegin', html);
  }

  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // --- Animated Counters (for fact check scores) ---
  document.querySelectorAll('.fc-score__fill').forEach(function(el) {
    var width = el.getAttribute('data-width');
    if (width) {
      var obs = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
          if (entry.isIntersecting) {
            entry.target.style.width = width;
            obs.unobserve(entry.target);
          }
        });
      }, { threshold: 0.3 });
      el.style.width = '0%';
      obs.observe(el);
    }
  });

})();
