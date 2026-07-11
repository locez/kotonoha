# build_bridge.sh does not emit source mappings for an RPM debugsource package.
%global debug_package %{nil}

Name:           kotonoha
Version:        0.1.0
Release:        1%{?dist}
Summary:        Desktop lyrics overlay for Linux

License:        MIT AND BSD-2-Clause
URL:            https://github.com/locez/kotonoha
Source0:        %{name}-%{version}.tar.gz
Source1:        qasync-0.28.0-py3-none-any.whl

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
Requires:       python3-pyqt6
Requires:       python3-aiohttp
Requires:       python3-dbus-fast
Requires:       layer-shell-qt
Provides:       bundled(python3dist(qasync)) = 0.28.0

%description
Kotonoha displays synchronized lyrics for the currently playing track in a
Wayland layer-shell overlay.

%prep
%autosetup
sed -i 's/^requires = \["hatchling", "hatch-build-scripts"\]$/requires = ["hatchling"]/' pyproject.toml
sed -i '/^\[tool\.hatch\.build\.hooks\.build-scripts\]$/,/^artifacts = \["src\/kotonoha\/libkoto-layer\.so"\]$/d' pyproject.toml

%build
USE_SYSTEM_LIBS=1 bash src/kotonoha/build_bridge.sh
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files kotonoha
python3 -m zipfile -e %{SOURCE1} %{buildroot}%{python3_sitelib}
install -Dm0644 packaging/kotonoha.desktop \
    %{buildroot}%{_datadir}/applications/kotonoha.desktop
install -Dm0644 src/kotonoha/assets/icon.png \
    %{buildroot}%{_datadir}/pixmaps/kotonoha.png

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/kotonoha.desktop

%files -f %{pyproject_files}
%doc README.md
%{_bindir}/kotonoha
%{python3_sitelib}/qasync/
%dir %{python3_sitelib}/qasync-0.28.0.dist-info
%{python3_sitelib}/qasync-0.28.0.dist-info/METADATA
%{python3_sitelib}/qasync-0.28.0.dist-info/RECORD
%{python3_sitelib}/qasync-0.28.0.dist-info/WHEEL
%dir %{python3_sitelib}/qasync-0.28.0.dist-info/licenses
%license %{python3_sitelib}/qasync-0.28.0.dist-info/licenses/LICENSE
%{_datadir}/applications/kotonoha.desktop
%{_datadir}/pixmaps/kotonoha.png

%changelog
* Sat Jul 11 2026 Locez <locez@locez.com> - 0.1.0-1
- Initial package
