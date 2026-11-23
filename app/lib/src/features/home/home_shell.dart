import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../l10n/generated/app_localizations.dart';

/// Bottom navigation for the signed-in workspace. More sections join in N-04..N-06.
class HomeShell extends StatelessWidget {
  const HomeShell({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Scaffold(
      body: navigationShell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: navigationShell.currentIndex,
        onDestinationSelected: (index) =>
            navigationShell.goBranch(index, initialLocation: index == navigationShell.currentIndex),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.space_dashboard_outlined),
            selectedIcon: const Icon(Icons.space_dashboard),
            label: l.nav_dashboard,
          ),
          NavigationDestination(
            icon: const Icon(Icons.folder_outlined),
            selectedIcon: const Icon(Icons.folder),
            label: l.nav_projects,
          ),
          NavigationDestination(
            icon: const Icon(Icons.forum_outlined),
            selectedIcon: const Icon(Icons.forum),
            label: l.app_chatsTab,
          ),
          NavigationDestination(
            icon: const Icon(Icons.person_outline),
            selectedIcon: const Icon(Icons.person),
            label: l.nav_profile,
          ),
        ],
      ),
    );
  }
}
