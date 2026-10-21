function mountTrainingBanner() {
    const source = document.querySelector('.toe-training-wrap:not(.toe-training-floating)');
    if (!source || document.querySelector('.toe-training-floating'))
        return () => { };
    const storageKey = 'toe-training-banner-dismissed-20261021';
    try {
        if (sessionStorage.getItem(storageKey) === '1')
            return () => { };
    }
    catch { }
    const floating = source.cloneNode(true);
    floating.classList.add('toe-training-floating');
    floating.setAttribute('aria-label', 'PR｜TOEのAI研修・追従バナー');
    floating.hidden = true;
    floating.querySelectorAll('script').forEach(node => node.remove());
    const link = floating.querySelector('.toe-training-banner');
    const url = new URL(link.href);
    url.searchParams.set('utm_content', 'scroll_banner');
    link.href = url.href;
    const action = link.querySelector('.toe-training-action');
    link.append(action);
    const close = document.createElement('button');
    close.className = 'toe-training-close';
    close.type = 'button';
    close.setAttribute('aria-label', 'AI研修の広告を閉じる');
    close.textContent = '×';
    floating.append(close);
    const spacer = document.createElement('div');
    spacer.setAttribute('aria-hidden', 'true');
    document.body.append(floating, spacer);
    let dismissed = false;
    const update = () => {
        const rect = source.getBoundingClientRect();
        const inlineVisible = rect.bottom > 0 && rect.top < innerHeight;
        const focused = document.activeElement;
        const editing = focused instanceof HTMLElement && (focused.matches('input,textarea,select') || focused.isContentEditable);
        const visible = scrollY > 320 && !inlineVisible && !dismissed && !editing;
        floating.hidden = !visible;
        const offset = visible ? floating.getBoundingClientRect().height + 24 : 0;
        document.documentElement.style.setProperty('--toe-training-offset', offset + 'px');
        spacer.style.height = offset + 'px';
    };
    const events = new AbortController();
    addEventListener('scroll', update, { passive: true, signal: events.signal });
    addEventListener('resize', update, { passive: true, signal: events.signal });
    document.addEventListener('focusin', update, { signal: events.signal });
    document.addEventListener('focusout', () => requestAnimationFrame(update), { signal: events.signal });
    close.addEventListener('click', () => {
        dismissed = true;
        try {
            sessionStorage.setItem(storageKey, '1');
        }
        catch { }
        update();
    }, { signal: events.signal });
    const observer = new IntersectionObserver(update);
    observer.observe(source);
    update();
    return () => {
        events.abort();
        observer.disconnect();
        floating.remove();
        spacer.remove();
        document.documentElement.style.removeProperty('--toe-training-offset');
    };
}

if(document.readyState === "loading")document.addEventListener("DOMContentLoaded",()=>mountTrainingBanner(),{once:true});else mountTrainingBanner();
