/* ============================================================
   NOAH WIRE — Interactions & Animations
   ============================================================ */

(function() {
  'use strict';

  // --- Scroll Reveal (IntersectionObserver) ---
  function initReveal() {
    var targets = document.querySelectorAll('.reveal, .reveal--left, .reveal--right, .reveal--scale');
    if (!targets.length) return;

    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      });
    }, {
      threshold: 0.12,
      rootMargin: '0px 0px -40px 0px'
    });

    targets.forEach(function(el) { observer.observe(el); });
  }

  // --- Sticky Nav ---
  function initNav() {
    var nav = document.querySelector('.nav');
    if (!nav) return;

    var scrolled = false;
    function checkScroll() {
      var shouldBeScrolled = window.scrollY > 60;
      if (shouldBeScrolled !== scrolled) {
        scrolled = shouldBeScrolled;
        nav.classList.toggle('scrolled', scrolled);
      }
    }
    window.addEventListener('scroll', checkScroll, { passive: true });
    checkScroll();
  }

  // --- Mobile Menu ---
  function initMobileMenu() {
    var toggle = document.querySelector('.nav__toggle');
    var mobile = document.querySelector('.nav__mobile');
    if (!toggle || !mobile) return;

    var isOpen = false;
    toggle.addEventListener('click', function() {
      isOpen = !isOpen;
      mobile.classList.toggle('open', isOpen);
      toggle.classList.toggle('active', isOpen);
      document.body.style.overflow = isOpen ? 'hidden' : '';
    });

    mobile.querySelectorAll('a').forEach(function(link) {
      link.addEventListener('click', function() {
        isOpen = false;
        mobile.classList.remove('open');
        toggle.classList.remove('active');
        document.body.style.overflow = '';
      });
    });
  }

  // --- Animated Stat Counter ---
  function initCounters() {
    var counters = document.querySelectorAll('[data-count]');
    if (!counters.length) return;

    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          animateCounter(entry.target);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });

    counters.forEach(function(el) { observer.observe(el); });
  }

  function animateCounter(el) {
    var target = parseInt(el.getAttribute('data-count'), 10);
    var suffix = el.getAttribute('data-suffix') || '';
    var prefix = el.getAttribute('data-prefix') || '';
    var duration = 1800;
    var start = performance.now();

    function easeOutExpo(t) {
      return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
    }

    function tick(now) {
      var progress = Math.min((now - start) / duration, 1);
      var eased = easeOutExpo(progress);
      var current = Math.round(eased * target);
      el.textContent = prefix + current + suffix;

      if (progress < 1) {
        requestAnimationFrame(tick);
      }
    }

    requestAnimationFrame(tick);
  }

  // --- Smooth Scroll for anchor links ---
  function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function(link) {
      link.addEventListener('click', function(e) {
        var targetId = this.getAttribute('href');
        if (targetId === '#') return;
        var target = document.querySelector(targetId);
        if (target) {
          e.preventDefault();
          var navHeight = document.querySelector('.nav') ? document.querySelector('.nav').offsetHeight : 0;
          var top = target.getBoundingClientRect().top + window.scrollY - navHeight;
          window.scrollTo({ top: top, behavior: 'smooth' });
        }
      });
    });
  }

  // --- Active Nav Link ---
  function initActiveNav() {
    var path = window.location.pathname.split('/').pop() || 'index.html';
    document.querySelectorAll('.nav__link').forEach(function(link) {
      var href = link.getAttribute('href');
      if (href === path || (path === 'index.html' && href === '/') ||
          (path === '' && href === 'index.html')) {
        link.classList.add('active');
      }
    });
  }

  // --- Typewriter effect for hero (optional, subtle) ---
  function initHeroReveal() {
    var headline = document.querySelector('.hero__headline');
    var subtitle = document.querySelector('.hero__subtitle');
    var ctas = document.querySelector('.hero__ctas');
    var hint = document.querySelector('.hero__scroll-hint');

    if (headline) {
      headline.style.opacity = '0';
      headline.style.transform = 'translateY(20px)';
      setTimeout(function() {
        headline.style.transition = 'opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1), transform 0.8s cubic-bezier(0.16, 1, 0.3, 1)';
        headline.style.opacity = '1';
        headline.style.transform = 'translateY(0)';
      }, 200);
    }

    if (subtitle) {
      subtitle.style.opacity = '0';
      subtitle.style.transform = 'translateY(20px)';
      setTimeout(function() {
        subtitle.style.transition = 'opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1), transform 0.8s cubic-bezier(0.16, 1, 0.3, 1)';
        subtitle.style.opacity = '1';
        subtitle.style.transform = 'translateY(0)';
      }, 500);
    }

    if (ctas) {
      ctas.style.opacity = '0';
      ctas.style.transform = 'translateY(20px)';
      setTimeout(function() {
        ctas.style.transition = 'opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1), transform 0.8s cubic-bezier(0.16, 1, 0.3, 1)';
        ctas.style.opacity = '1';
        ctas.style.transform = 'translateY(0)';
      }, 750);
    }

    if (hint) {
      hint.style.opacity = '0';
      setTimeout(function() {
        hint.style.transition = 'opacity 1.2s ease';
        hint.style.opacity = '1';
      }, 1500);
    }
  }

  // --- RSS News Loader (for news section on homepage) ---
  function initNewsLoader() {
    var container = document.querySelector('[data-news-feed]');
    if (!container) return;

    var feeds = [
      'https://noah.makes.news/section/663bf0becee334cd1f1a4bcf/rss.xml',
      'https://noah.makes.news/section/663bee09cee334cd1f1a4bca/rss.xml'
    ];

    var allItems = [];

    function parseRSS(xml) {
      var items = xml.querySelectorAll('item');
      var parsed = [];
      items.forEach(function(item) {
        var title = item.querySelector('title') ? item.querySelector('title').textContent : '';
        var link = item.querySelector('link') ? item.querySelector('link').textContent : '';
        var desc = item.querySelector('description') ? item.querySelector('description').textContent : '';
        var date = item.querySelector('pubDate') ? item.querySelector('pubDate').textContent : '';
        var enclosure = item.querySelector('enclosure');
        var image = enclosure ? enclosure.getAttribute('url') : '';

        // Strip HTML from description to get plain text excerpt
        var tmp = document.createElement('div');
        tmp.innerHTML = desc;
        var plainText = tmp.textContent || tmp.innerText || '';
        var excerpt = plainText.substring(0, 160).trim() + '...';

        parsed.push({
          title: title,
          link: link,
          excerpt: excerpt,
          date: new Date(date),
          image: image
        });
      });
      return parsed;
    }

    var loaded = 0;
    feeds.forEach(function(feedUrl) {
      // Use a CORS proxy or direct fetch (same-origin issues may apply)
      fetch(feedUrl)
        .then(function(r) { return r.text(); })
        .then(function(text) {
          var parser = new DOMParser();
          var xml = parser.parseFromString(text, 'text/xml');
          allItems = allItems.concat(parseRSS(xml));
          loaded++;
          if (loaded === feeds.length) renderNews(allItems);
        })
        .catch(function() {
          loaded++;
          if (loaded === feeds.length && allItems.length > 0) renderNews(allItems);
        });
    });

    function renderNews(items) {
      items.sort(function(a, b) { return b.date - a.date; });
      var html = '';
      items.slice(0, 6).forEach(function(item) {
        var dateStr = item.date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
        html += '<article class="news-card reveal">';
        if (item.image) {
          html += '<div class="news-card__image img-frame"><img src="' + item.image + '" alt="" loading="lazy"></div>';
        }
        html += '<div class="news-card__body">';
        html += '<time class="news-card__date">' + dateStr + '</time>';
        html += '<h3 class="news-card__title"><a href="' + item.link + '" target="_blank" rel="noopener">' + item.title + '</a></h3>';
        html += '<p class="news-card__excerpt">' + item.excerpt + '</p>';
        html += '</div></article>';
      });
      container.innerHTML = html;
      // Re-init reveal for new elements
      initReveal();
    }
  }

  // --- Init ---
  document.addEventListener('DOMContentLoaded', function() {
    initNav();
    initMobileMenu();
    initHeroReveal();
    initReveal();
    initCounters();
    initSmoothScroll();
    initActiveNav();
    initNewsLoader();
  });

})();
