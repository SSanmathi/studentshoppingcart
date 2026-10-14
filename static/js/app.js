document.addEventListener('DOMContentLoaded', function () {
    const toasts = document.querySelectorAll('.toast');
    toasts.forEach((toast) => {
        setTimeout(() => {
            toast.classList.add('is-dismissing');
            toast.addEventListener('transitionend', () => toast.remove(), { once: true });
            setTimeout(() => toast.remove(), 450);
        }, 3200);
    });

    const productSearchInput = document.getElementById('product-search-input');
    const clearProductSearch = document.getElementById('clear-product-search');
    const resultCount = document.getElementById('product-result-count');
    const productGrid = document.getElementById('product-grid');
    const emptyState = document.getElementById('no-products-found');
    const filterForm = document.querySelector('.filter-form');
    const minPriceInput = filterForm?.querySelector('input[name="min_price"]');
    const maxPriceInput = filterForm?.querySelector('input[name="max_price"]');
    const stockInput = filterForm?.querySelector('input[name="stock"]');

    if (productSearchInput && productGrid && resultCount) {
        const cards = Array.from(productGrid.querySelectorAll('.product-card'));
        const initialSearchQuery = productSearchInput.value.trim();
        const applyFilter = () => {
            const query = productSearchInput.value.trim().toLowerCase();
            const priceMatch = query.match(/\bunder\s*₹?\s*(\d+(?:\.\d+)?)/);
            const textQuery = priceMatch
                ? `${query.slice(0, priceMatch.index)} ${query.slice(priceMatch.index + priceMatch[0].length)}`.trim()
                : query;
            const enteredMaxPrice = maxPriceInput?.value.trim();
            const maxPriceValues = [
                priceMatch ? Number(priceMatch[1]) : null,
                enteredMaxPrice ? Number(enteredMaxPrice) : null,
            ].filter((price) => price !== null && Number.isFinite(price));
            const maxFilterPrice = maxPriceValues.length ? Math.min(...maxPriceValues) : null;
            const enteredMinPrice = minPriceInput?.value.trim();
            const minFilterPrice = enteredMinPrice ? Number(enteredMinPrice) : null;
            const onlyInStock = Boolean(stockInput?.checked);
            let visibleCards = 0;

            cards.forEach((card) => {
                const searchableText = (card.dataset.search || card.textContent || '').toLowerCase();
                const matchesText = !textQuery || searchableText.includes(textQuery);
                const price = Number(card.dataset.price);
                const matchesPrice = (maxFilterPrice === null || price <= maxFilterPrice)
                    && (minFilterPrice === null || price >= minFilterPrice);
                const matchesStock = !onlyInStock || Number(card.dataset.stock) > 0;
                const match = matchesText && matchesPrice && matchesStock;
                card.style.display = match ? '' : 'none';
                if (match) {
                    visibleCards += 1;
                }
            });

            resultCount.textContent = `${visibleCards} product${visibleCards === 1 ? '' : 's'}`;
            if (emptyState) {
                emptyState.hidden = visibleCards !== 0;
            }
        };
        const clearSearch = () => {
            productSearchInput.value = '';
            if (initialSearchQuery && productSearchInput.form) {
                if (typeof productSearchInput.form.requestSubmit === 'function') {
                    productSearchInput.form.requestSubmit();
                } else {
                    productSearchInput.form.submit();
                }
                return;
            }
            applyFilter();
            productSearchInput.focus();
        };

        productSearchInput.addEventListener('input', applyFilter);
        [minPriceInput, maxPriceInput].forEach((input) => {
            if (input) input.addEventListener('input', applyFilter);
        });
        if (clearProductSearch) {
            clearProductSearch.addEventListener('click', clearSearch);
        }
        productSearchInput.addEventListener('keyup', function (event) {
            if (event.key === 'Escape') {
                clearSearch();
            }
        });
        applyFilter();
    }

    document.querySelectorAll('.filter-form').forEach((form) => {
        form.querySelectorAll('select, input[name="stock"]').forEach((control) => {
            control.addEventListener('change', () => {
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    form.submit();
                }
            });
        });
    });

    document.querySelectorAll('.global-search-input').forEach((searchInput) => {
        const searchContainer = searchInput.closest('.search-box, .global-search');
        const suggestions = searchContainer ? searchContainer.querySelector('.search-suggestions') : null;
        if (!suggestions) return;
        let searchTimer;
        let suggestionRequest = 0;
        searchInput.addEventListener('input', function () {
            const query = searchInput.value.trim();
            window.clearTimeout(searchTimer);
            if (query.length < 2) {
                suggestions.replaceChildren();
                suggestions.classList.remove('visible');
                return;
            }
            searchTimer = window.setTimeout(async function () {
                const requestId = ++suggestionRequest;
                try {
                    const response = await fetch(`/api/products?q=${encodeURIComponent(query)}`);
                    if (!response.ok) throw new Error(`Search request failed (${response.status})`);
                    const products = await response.json();
                    if (requestId !== suggestionRequest) return;
                    suggestions.replaceChildren();
                    products.forEach((product) => {
                        const link = document.createElement('a');
                        link.className = 'search-suggestion';
                        link.href = `/product/${encodeURIComponent(product.id)}`;
                        const image = document.createElement('img');
                        image.src = product.image_url;
                        image.alt = '';
                        image.onerror = function () {
                            image.onerror = null;
                            const fallbacks = {
                                Books: '/static/images/books-image-fallback.svg',
                                'Hostel Essentials': '/static/images/hostel-image-fallback.svg',
                            };
                            image.src = fallbacks[product.category]
                                || '/static/images/stationery-image-fallback.svg';
                        };
                        const name = document.createElement('span');
                        name.textContent = product.name;
                        const price = document.createElement('strong');
                        const currentPrice = Number(product.effective_price ?? product.price);
                        price.textContent = `₹${currentPrice.toFixed(2)}`;
                        link.append(image, name, price);
                        suggestions.append(link);
                    });
                    if (!products.length) {
                        const empty = document.createElement('p');
                        empty.className = 'search-suggestion-empty';
                        empty.textContent = 'No matching products. Try another search.';
                        suggestions.append(empty);
                    }
                    suggestions.classList.add('visible');
                } catch (error) {
                    suggestions.replaceChildren();
                    const empty = document.createElement('p');
                    empty.className = 'search-suggestion-empty';
                    empty.textContent = 'Search is temporarily unavailable. Press Enter to view results.';
                    suggestions.append(empty);
                    suggestions.classList.add('visible');
                    console.error(error);
                }
            }, 140);
        });
        const clearButton = searchContainer.querySelector('#clear-product-search');
        if (clearButton && searchInput !== productSearchInput) {
            clearButton.addEventListener('click', function () {
                searchInput.value = '';
                suggestions.replaceChildren();
                suggestions.classList.remove('visible');
                searchInput.focus();
                searchInput.dispatchEvent(new Event('input', { bubbles: true }));
            });
        }
        searchInput.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') suggestions.classList.remove('visible');
        });
        document.addEventListener('click', function (event) {
            if (!suggestions.contains(event.target) && !searchInput.contains(event.target)) {
                suggestions.classList.remove('visible');
            }
        });
    });

    const cartItems = Array.from(document.querySelectorAll('.cart-item-card'));
    const cartSubtotal = document.getElementById('cart-subtotal');
    const cartTotal = document.getElementById('cart-total');
    const cartDiscount = document.getElementById('cart-discount');
    const cartBudget = document.querySelector('.cart-budget-summary');
    if (cartItems.length && cartSubtotal && cartTotal && cartBudget) {
        const refreshCartPreview = function () {
            let subtotal = 0;
            let discount = 0;
            cartItems.forEach((item) => {
                const quantity = Number(item.querySelector('input[name="quantity"]')?.value || 0);
                const safeQuantity = Math.max(0, quantity);
                const listPrice = Number(item.dataset.unitPrice);
                const lineSubtotal = Math.round((listPrice * safeQuantity + Number.EPSILON) * 100) / 100;
                const offers = JSON.parse(item.dataset.availableOffers || '[]');
                let unitDiscount = 0;
                offers.forEach((offer) => {
                    if (safeQuantity < Number(offer.min_quantity || 1)) return;
                    const candidate = offer.offer_type === 'percentage'
                        ? Math.round((listPrice * Number(offer.value) / 100 + Number.EPSILON) * 100) / 100
                        : Number(offer.value);
                    unitDiscount = Math.max(unitDiscount, Math.min(candidate, listPrice));
                });
                const lineDiscount = Math.round((unitDiscount * safeQuantity + Number.EPSILON) * 100) / 100;
                const lineTotal = Math.max(0, lineSubtotal - lineDiscount);
                subtotal += lineSubtotal;
                discount += lineDiscount;
                const lineAmount = item.querySelector('.cart-item-price strong');
                if (lineAmount) lineAmount.textContent = `₹${lineTotal.toFixed(2)}`;
                const unitPrice = item.querySelector('.cart-unit-price');
                if (unitPrice) unitPrice.textContent = `₹${(listPrice - unitDiscount).toFixed(2)} each`;
                const listTotal = item.querySelector('.cart-list-total');
                if (listTotal) {
                    listTotal.textContent = `List price total: ₹${lineSubtotal.toFixed(2)}`;
                    listTotal.hidden = lineDiscount <= 0;
                }

            });
            subtotal = Math.round((subtotal + Number.EPSILON) * 100) / 100;
            discount = Math.round((discount + Number.EPSILON) * 100) / 100;
            const budget = Number(cartBudget.dataset.budget || 0);
            const total = Math.max(0, subtotal - discount);
            const remaining = budget - total;
            cartSubtotal.textContent = `₹${subtotal.toFixed(2)}`;
            cartTotal.textContent = `₹${total.toFixed(2)}`;
            if (cartDiscount) cartDiscount.textContent = `-₹${discount.toFixed(2)}`;
            document.querySelectorAll('.live-budget-remaining').forEach((element) => {
                element.textContent = `₹${remaining.toFixed(2)}`;
            });
            const warning = cartBudget.querySelector('.budget-warning');
            if (warning) warning.hidden = remaining >= 0;
        };
        cartItems.forEach((item) => {
            const quantityInput = item.querySelector('input[name="quantity"]');
            if (quantityInput) quantityInput.addEventListener('input', refreshCartPreview);
        });
        refreshCartPreview();
    }

    const deliveryType = document.getElementById('delivery_type');
    const deliveryAddress = document.getElementById('delivery_address');
    if (deliveryType && deliveryAddress) {
        const updateDeliveryAddress = () => {
            const isDelivery = deliveryType.value === 'delivery';
            deliveryAddress.required = isDelivery;
            deliveryAddress.disabled = !isDelivery;
            if (!isDelivery) deliveryAddress.value = '';
        };
        deliveryType.addEventListener('change', updateDeliveryAddress);
        updateDeliveryAddress();
    }

    const kitForm = document.getElementById('kit-form');
    const kitBudgetInput = document.getElementById('kit-budget');
    if (kitForm && kitBudgetInput) {
        const kitProducts = Array.from(kitForm.querySelectorAll('.kit-product'));
        const totalElement = document.getElementById('kit-total');
        const remainingElement = document.getElementById('kit-remaining');
        const warningElement = document.getElementById('kit-budget-warning');
        const countElement = document.getElementById('kit-visible-count');
        const submitButton = kitForm.querySelector('button[type="submit"]');
        const refreshKit = function () {
            let total = 0;
            const selectedProducts = [];
            kitProducts.forEach((product) => {
                const checkbox = product.querySelector('input[type="checkbox"]');
                if (checkbox.checked) {
                    total += Number(checkbox.dataset.price);
                    selectedProducts.push(product);
                }
            });
            const budget = Math.max(0, Number(kitBudgetInput.value) || 0);
            const remaining = budget - total;
            const budgetField = kitForm.querySelector('input[name="kit_budget"]');
            if (budgetField) budgetField.value = budgetInputValue();
            totalElement.textContent = `₹${total.toFixed(2)}`;
            remainingElement.textContent = `₹${remaining.toFixed(2)}`;
            warningElement.hidden = remaining >= 0;
            countElement.textContent = `${kitProducts.length} available`;
            kitProducts.forEach((product) => {
                const checkbox = product.querySelector('input[type="checkbox"]');
                checkbox.disabled = !checkbox.checked && Number(checkbox.dataset.price) > remaining;
            });
            if (submitButton) submitButton.disabled = total <= 0 || remaining < 0;

            let alternatives = document.getElementById('kit-alternatives');
            if (alternatives) {
                alternatives.replaceChildren();
                const replacements = selectedProducts.flatMap((selected) => {
                    const selectedPrice = Number(selected.dataset.price);
                    return kitProducts
                        .filter((candidate) => candidate !== selected
                            && candidate.dataset.category === selected.dataset.category
                            && Number(candidate.dataset.price) < selectedPrice
                            && Number(candidate.dataset.price) <= budget)
                        .sort((left, right) => Number(left.dataset.price) - Number(right.dataset.price))
                        .slice(0, 1)
                        .map((candidate) => ({ selected, candidate }));
                });
                if (replacements.length) {
                    const label = document.createElement('strong');
                    label.textContent = 'Cheaper alternatives in the same category: ';
                    alternatives.append(label);
                    replacements.forEach(({ selected, candidate }) => {
                        const link = document.createElement('a');
                        link.href = candidate.querySelector('.product-image-link').href;
                        link.textContent = `${candidate.querySelector('h3').textContent} instead of ${selected.querySelector('h3').textContent} (₹${Number(candidate.dataset.price).toFixed(2)})`;
                        alternatives.append(link);
                    });
                } else {
                    alternatives.textContent = selectedProducts.length
                        ? 'No lower-priced alternative in the selected products’ categories is available within this budget.'
                        : 'Select products to see lower-priced alternatives in their categories.';
                }
            }
        };
        const budgetInputValue = () => (Number(kitBudgetInput.value) || 0).toFixed(2);
        kitBudgetInput.addEventListener('input', refreshKit);
        kitProducts.forEach((product) => {
            product.querySelector('input[type="checkbox"]').addEventListener('change', refreshKit);
        });
        refreshKit();
    }

    const moveInForm = document.getElementById('move-in-form');
    if (moveInForm) {
        const checklistItems = Array.from(moveInForm.querySelectorAll('.move-in-checklist-item'));
        const estimateElement = document.getElementById('move-in-estimate');
        const selectedTotalElement = document.getElementById('move-in-selected-total');
        const refreshMoveIn = function () {
            let missingTotal = 0;
            const selectedById = new Map();
            checklistItems.forEach((item) => {
                const owned = item.querySelector('input[name="owned_items"]');
                const estimate = Number(item.dataset.estimatedPrice || 0);
                if (!owned.checked) missingTotal += estimate;
                item.querySelectorAll('input[name="product_ids"]').forEach((checkbox) => {
                    if (checkbox.checked) selectedById.set(checkbox.value, Number(checkbox.dataset.price));
                });
            });
            const cartSelectionTotal = Array.from(selectedById.values()).reduce((sum, price) => sum + price, 0);
            if (estimateElement) estimateElement.textContent = `₹${missingTotal.toFixed(2)}`;
            if (selectedTotalElement) selectedTotalElement.textContent = `₹${cartSelectionTotal.toFixed(2)}`;
        };
        moveInForm.addEventListener('change', function (event) {
            if (event.target.matches('input[name="product_ids"]')) {
                const sameProduct = moveInForm.querySelectorAll(`input[name="product_ids"][value="${CSS.escape(event.target.value)}"]`);
                sameProduct.forEach((checkbox) => { checkbox.checked = event.target.checked; });
            }
            refreshMoveIn();
        });
        refreshMoveIn();
    }

    const challengeForm = document.getElementById('challenge-form');
    if (challengeForm) {
        const items = Array.from(challengeForm.querySelectorAll('.challenge-product'));
        const totalElement = document.getElementById('challenge-total');
        const remainingElement = document.getElementById('challenge-remaining');
        const warningElement = document.getElementById('challenge-warning');
        const submitButton = challengeForm.querySelector('button[type="submit"]');
        const budget = Number(challengeForm.querySelector('input[name="budget"]').value);
        const refreshChallenge = function () {
            let total = 0;
            items.forEach((item) => {
                const checkbox = item.querySelector('input[type="checkbox"]');
                if (checkbox.checked) total += Number(checkbox.dataset.price);
            });
            const remaining = budget - total;
            totalElement.textContent = `₹${total.toFixed(2)}`;
            remainingElement.textContent = `₹${remaining.toFixed(2)}`;
            warningElement.hidden = remaining >= 0;
            items.forEach((item) => {
                const checkbox = item.querySelector('input[type="checkbox"]');
                checkbox.disabled = !checkbox.checked && Number(checkbox.dataset.price) > remaining;
            });
            if (submitButton) submitButton.disabled = total <= 0 || remaining < 0;
        };
        challengeForm.addEventListener('change', refreshChallenge);
        refreshChallenge();
    }

    document.querySelectorAll('.qty-btn').forEach((button) => {
        button.addEventListener('click', function () {
            const parent = this.closest('.qty-control');
            const input = parent.querySelector('input');
            const current = Number(input.value || 1);
            const min = Number(input.min || 1);
            const max = Number(input.max || 999);
            const action = this.dataset.action;

            let nextValue = current;
            if (action === 'plus') {
                nextValue = Math.min(current + 1, max);
            } else if (action === 'minus') {
                nextValue = Math.max(current - 1, min);
            }

            input.value = nextValue;
        });
    });
});
