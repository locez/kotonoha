Name:           kotonoha
Version:        0.1.0
Release:        1%{?dist}
Summary:        Desktop lyrics overlay for Linux

License:        MIT
URL:            https://github.com/locez/kotonoha
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz

BuildRequires:  python3-devel
BuildRequires:  python3-hatchling
BuildRequires:  pyproject-rpm-macros
BuildRequires:  gcc-c++
BuildRequires:  qt6-qtbase-devel
BuildRequires:  qt6-qtbase-private-devel
BuildRequires:  qt6-qtwayland-devel
BuildRequires:  layer-shell-qt-devel
BuildRequires:  wayland-devel
BuildRequires:  desktop-file-utils
Requires:       python3
Requires:       python3-qt6
Requires:       python3-aiohttp
Requires:       python3-qasync
Requires:       python3-dbus-fast
Requires:       layer-shell-qt

%description
Kotonoha displays synchronized lyrics for the currently playing track in a
Wayland layer-shell overlay.

%prep
%autosetup

%build
export PYTHONPATH="/usr/local/lib/python%{python3_version}/site-packages${PYTHONPATH:+:${PYTHONPATH}}"
export USE_SYSTEM_LIBS=1
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files kotonoha
install -Dm0644 packaging/kotonoha.desktop \
    %{buildroot}%{_datadir}/applications/kotonoha.desktop
install -Dm0644 src/kotonoha/assets/icon.png \
    %{buildroot}%{_datadir}/pixmaps/kotonoha.png

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/kotonoha.desktop

%files -f %{pyproject_files}
%doc README.md
%{_bindir}/kotonoha
%{_datadir}/applications/kotonoha.desktop
%{_datadir}/pixmaps/kotonoha.png

%changelog
* Sat Jul 11 2026 Locez <locez@locez.com> - 0.1.0-1
- Initial package
