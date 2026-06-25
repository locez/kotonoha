// Kotonoha Wayland layer-shell bridge.
//
// Compiled to libkoto-layer.so and loaded from Python via ctypes (see
// native.py / overlay.py). Promotes a QWindow to a wlr-layer-shell Overlay
// surface so the lyrics float above fullscreen apps, and exposes click-through
// (input region) + positioning control.
//
// IMPORTANT: make_overlay() must run BEFORE the window is shown, otherwise the
// surface already has an xdg-shell role and LayerShellQt refuses to convert it
// ("already has a shell integration"). overlay.py calls activate before show().
//
// Modelled on BiliHUD's bridge: anchor Top|Left and position the fixed-size
// surface with left/top margins (set_anchor_position), which is what makes the
// panel freely draggable.

#include <QWindow>
#include <LayerShellQt/Window>

#include <QMargins>

#include <QGuiApplication>
#include <qpa/qplatformnativeinterface.h>
#include <wayland-client.h>


extern "C" {
    void make_overlay(void* window_ptr) {
        if (!window_ptr) return;

        QWindow* window = static_cast<QWindow*>(window_ptr);
        LayerShellQt::Window* ls_window = LayerShellQt::Window::get(window);

        if (ls_window) {
            ls_window->setLayer(LayerShellQt::Window::LayerOverlay);
            // -1 for no exclusive zone (fully ignored by tiling layout).
            ls_window->setExclusiveZone(-1);
            // Lyrics are passive; no keyboard focus.
            ls_window->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
            // Anchor to the top-left corner; the surface keeps its requested size
            // and is positioned by left/top margins (set_anchor_position).
            ls_window->setAnchors(LayerShellQt::Window::Anchors(
                LayerShellQt::Window::AnchorTop | LayerShellQt::Window::AnchorLeft));
            ls_window->setScope("kotonoha");
        }
    }

    // Position the surface via left/top margins (x, y from the top-left anchor).
    void set_anchor_position(void* window_ptr, int x, int y) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);
        LayerShellQt::Window* ls_window = LayerShellQt::Window::get(window);

        if (ls_window) {
            QMargins margins;
            margins.setLeft(x);
            margins.setTop(y);
            margins.setRight(0);
            margins.setBottom(0);
            ls_window->setMargins(margins);
        }
    }

    void set_passthrough(void* window_ptr, bool enabled) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);

        QPlatformNativeInterface* native = QGuiApplication::platformNativeInterface();
        if (!native) return;

        struct wl_surface* surface = (struct wl_surface*)native->nativeResourceForWindow("surface", window);
        if (!surface) return;

        struct wl_compositor* compositor = (struct wl_compositor*)native->nativeResourceForIntegration("compositor");
        if (!compositor) {
            compositor = (struct wl_compositor*)native->nativeResourceForIntegration("wl_compositor");
        }

        if (surface && compositor) {
            if (enabled) {
                // Empty input region -> surface accepts no input (click-through).
                struct wl_region* region = wl_compositor_create_region(compositor);
                wl_surface_set_input_region(surface, region);
                wl_region_destroy(region);
            } else {
                // NULL input region -> infinite region (surface accepts all input).
                wl_surface_set_input_region(surface, nullptr);
            }
            wl_surface_commit(surface);
        }
    }

    void set_keyboard_interactivity(void* window_ptr, bool enabled) {
        if (!window_ptr) return;
        QWindow* window = static_cast<QWindow*>(window_ptr);
        LayerShellQt::Window* ls_window = LayerShellQt::Window::get(window);

        if (ls_window) {
            if (enabled) {
                ls_window->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityOnDemand);
            } else {
                ls_window->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
            }
        }
    }
}
