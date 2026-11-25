import 'dart:math';

import 'package:material_ui/material_ui.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';
import 'editor.dart';

const green = Color(0xff087f75);
const ink = Color(0xff203e36);
String day(DateTime d) => d.toIso8601String().substring(0, 10);
String fmt(dynamic n, [int places = 1]) =>
    n == null ? '—' : (n as num).toStringAsFixed(places);
IconData kindIcon(String kind) => switch (kind) {
  'transport' => Icons.train_outlined,
  'household' => Icons.home_outlined,
  _ => Icons.shopping_bag_outlined,
};

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const LiveGreen());
}

class LiveGreen extends StatelessWidget {
  const LiveGreen({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'LiveGreen',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: green,
        primary: green,
        surface: const Color(0xfffbfcf8),
      ),
      scaffoldBackgroundColor: const Color(0xfff3f6ee),
      textTheme: const TextTheme(
        headlineLarge: TextStyle(
          fontSize: 36,
          fontWeight: FontWeight.w600,
          color: ink,
          letterSpacing: -1.5,
        ),
        headlineMedium: TextStyle(
          fontSize: 28,
          fontWeight: FontWeight.w600,
          color: ink,
          letterSpacing: -.8,
        ),
        titleLarge: TextStyle(
          fontSize: 21,
          fontWeight: FontWeight.w600,
          color: ink,
        ),
        bodyMedium: TextStyle(fontSize: 14, color: ink, height: 1.5),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: Color(0xffd5dfd4)),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(minimumSize: const Size(48, 52)),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: Color(0xfff3f6ee),
        foregroundColor: ink,
        elevation: 0,
      ),
      navigationBarTheme: const NavigationBarThemeData(
        backgroundColor: Color(0xfffbfcf8),
        indicatorColor: Color(0xffd6e9d6),
      ),
    ),
    home: const GreenHome(),
  );
}

class GreenHome extends StatefulWidget {
  const GreenHome({super.key});
  @override
  State<GreenHome> createState() => _GreenHomeState();
}

class _GreenHomeState extends State<GreenHome> {
  final api = LiveGreenApi();
  final server = TextEditingController(), keyField = TextEditingController();
  Json? overview;
  List<Json> events = [], factors = [];
  DateTime end = DateTime(2026, 11, 22);
  int tab = 0, days = 7, requestId = 0;
  String filter = 'all', metric = 'co2e_kg';
  String? error;
  bool loading = true, connecting = false;
  DateTime? synced;
  DateTime get start => end.subtract(Duration(days: days - 1));

  @override
  void initState() {
    super.initState();
    initialize();
  }

  Future<void> initialize() async {
    try {
      await api.restore();
      server.text = api.base;
      if (api.connected) {
        api.account =
            (await api.request('/api/v1/activity-account'))['account'] as Json;
        if (api.account?['is_demo'] != true) {
          end = DateTime.now().toUtc().add(const Duration(hours: 8));
        }
      }
      await refresh();
      final lost = await ImagePicker().retrieveLostData();
      if (mounted && lost.files?.isNotEmpty == true) {
        if (api.connected) {
          await edit('shopping', recovered: lost.files!.first);
        } else {
          notice(
            'A receipt photo was recovered. Connect your account before saving it.',
          );
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          loading = false;
        });
      }
    }
  }

  @override
  void dispose() {
    requestId++;
    api.close();
    server.dispose();
    keyField.dispose();
    super.dispose();
  }

  void notice(String text) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  Future<void> refresh() async {
    final current = ++requestId;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final results = await Future.wait([
        api.overview(day(start), day(end)),
        api.events(day(start), day(end)),
        api.factors(),
      ]);
      if (!mounted || current != requestId) return;
      setState(() {
        overview = results[0] as Json;
        events = results[1] as List<Json>;
        factors = results[2] as List<Json>;
        api.account = overview!['account'] as Json;
        synced = DateTime.now();
      });
    } catch (e) {
      if (mounted && current == requestId) setState(() => error = e.toString());
    } finally {
      if (mounted && current == requestId) setState(() => loading = false);
    }
  }

  Future<void> connect() async {
    setState(() {
      connecting = true;
      error = null;
    });
    try {
      await api.connect(server.text, keyField.text);
      keyField.clear();
      setState(() {
        overview = null;
        events = [];
        factors = [];
        synced = null;
        end = api.account?['is_demo'] == true
            ? DateTime(2026, 11, 22)
            : DateTime.now().toUtc().add(const Duration(hours: 8));
        tab = 0;
      });
      await refresh();
      if (mounted) {
        notice('Account connected. Activities save to your database.');
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => connecting = false);
    }
  }

  Future<void> edit(String kind, {Json? original, XFile? recovered}) async {
    if (!api.connected) {
      setState(() => tab = 3);
      notice('Connect an activity account to save changes.');
      return;
    }
    if (loading || error != null) {
      notice('Refresh the connection before editing.');
      return;
    }
    final saved = await Navigator.push<Json>(
      context,
      MaterialPageRoute(
        builder: (_) => ActivityEditor(
          api: api,
          factors: factors,
          kind: kind,
          original: original,
          recovered: recovered,
        ),
      ),
    );
    if (saved == null || !mounted) return;
    if (saved['local_date'] != null) {
      end = DateTime.parse(saved['local_date'] as String);
    }
    setState(() => tab = 1);
    await refresh();
    if (mounted) notice('Activity saved · revision ${saved['revision']}');
  }

  Widget panel(Widget child, {Color color = Colors.white}) => Container(
    width: double.infinity,
    margin: const EdgeInsets.only(bottom: 16),
    padding: const EdgeInsets.all(22),
    decoration: BoxDecoration(
      color: color,
      borderRadius: BorderRadius.circular(26),
    ),
    child: child,
  );
  Widget heading(String text, {Widget? action}) => Padding(
    padding: const EdgeInsets.only(top: 12, bottom: 16),
    child: Row(
      children: [
        Expanded(
          child: Text(text, style: Theme.of(context).textTheme.titleLarge),
        ),
        ?action,
      ],
    ),
  );
  Widget section(
    String label,
    String subtitle,
    IconData icon,
    VoidCallback onTap,
  ) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Material(
      color: const Color(0xffe6eedc),
      borderRadius: BorderRadius.circular(24),
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 20,
          vertical: 14,
        ),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        leading: Icon(icon, color: green, size: 30),
        title: Text(label, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(subtitle),
        trailing: const Icon(Icons.arrow_forward_rounded),
        onTap: onTap,
      ),
    ),
  );

  Widget range() => Row(
    children: [
      IconButton(
        tooltip: 'Previous period',
        onPressed: loading
            ? null
            : () {
                setState(() => end = end.subtract(Duration(days: days)));
                refresh();
              },
        icon: const Icon(Icons.chevron_left),
      ),
      Expanded(
        child: TextButton(
          onPressed: loading
              ? null
              : () async {
                  final value = await showDatePicker(
                    context: context,
                    initialDate: end,
                    firstDate: DateTime(2020),
                    lastDate: DateTime(2030, 12, 31),
                  );
                  if (value != null && mounted) {
                    setState(() => end = value);
                    await refresh();
                  }
                },
          child: Text('${day(start).substring(5)} — ${day(end)}'),
        ),
      ),
      IconButton(
        tooltip: 'Next period',
        onPressed: loading
            ? null
            : () {
                setState(() => end = end.add(Duration(days: days)));
                refresh();
              },
        icon: const Icon(Icons.chevron_right),
      ),
    ],
  );

  Widget home() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        'Hello, ${api.account?['name'] ?? 'there'}.',
        style: Theme.of(context).textTheme.headlineLarge,
      ),
      const SizedBox(height: 8),
      const Text('A little more aware. A little greener.'),
      const SizedBox(height: 26),
      panel(
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'YOUR TRACKED FOOTPRINT',
              style: TextStyle(
                letterSpacing: 1.5,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 12),
            Text(
              '${fmt(overview?['total_kg'])} kg',
              style: Theme.of(context).textTheme.headlineLarge,
            ),
            const Text('CO₂e · selected period'),
            const SizedBox(height: 20),
            if (overview != null) chart('co2e_kg', height: 90),
            TextButton(
              onPressed: () => setState(() => tab = 2),
              child: const Text('See your footprint →'),
            ),
          ],
        ),
        color: const Color(0xffdceacb),
      ),
      heading('Add to your day'),
      section(
        'Shopping',
        'Scan a receipt or add items',
        Icons.shopping_bag_outlined,
        () => edit('shopping'),
      ),
      section(
        'Transportation',
        'Record a journey',
        Icons.train_outlined,
        () => edit('transport'),
      ),
      section(
        'At home',
        'Water and electricity',
        Icons.home_outlined,
        () => edit('household'),
      ),
      heading(
        'Needs your input',
        action: TextButton(
          onPressed: () => setState(() {
            filter = 'review';
            tab = 1;
          }),
          child: const Text('View all'),
        ),
      ),
      ...events
          .where((r) => r['status'] == 'needs_review')
          .take(2)
          .map(eventTile),
      if (!events.any((r) => r['status'] == 'needs_review'))
        const Text('Nothing waiting for review in this period.'),
    ],
  );

  Widget eventTile(Json r) => Card(
    elevation: 0,
    margin: const EdgeInsets.only(bottom: 10),
    color: Colors.white,
    child: ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      leading: Icon(kindIcon(r['kind'] as String), color: green),
      title: Text(
        r['name'] as String,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Text(
        '${r['local_date'] ?? 'Time unknown'} · ${(r['status'] as String).replaceAll('_', ' ')}',
      ),
      trailing: Text(
        r['co2e_kg'] == null ? '—' : '${fmt(r['co2e_kg'], 2)} kg',
        style: const TextStyle(fontWeight: FontWeight.w600),
      ),
      onTap: () => edit(r['kind'] as String, original: r),
    ),
  );

  Widget activities() {
    final visible = events
        .where(
          (r) =>
              filter == 'all' ||
              filter == 'review' && r['status'] == 'needs_review' ||
              r['kind'] == filter,
        )
        .toList()
        .reversed;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Your activities',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 8),
        const Text('A record you can understand and correct.'),
        const SizedBox(height: 20),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              for (final pair in [
                ('all', 'All'),
                ('review', 'Needs review'),
                ('shopping', 'Shopping'),
                ('transport', 'Transport'),
                ('household', 'Home'),
              ])
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(pair.$2),
                    selected: filter == pair.$1,
                    onSelected: (_) => setState(() => filter = pair.$1),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 20),
        ...visible.map(eventTile),
        if (visible.isEmpty)
          panel(
            const Text(
              'No activities here yet. Add one from Home, or change the date range.',
            ),
          ),
      ],
    );
  }

  Widget chart(String key, {double height = 150}) {
    final series = (overview!['series'] as List).cast<Json>();
    final maximum = max(
      .001,
      series.fold<double>(0, (v, r) => max(v, (r[key] as num).toDouble())),
    );
    return SizedBox(
      height: height + 32,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (final r in series)
            Expanded(
              child: Tooltip(
                message:
                    '${r['date']}: ${r['records'] == 0 ? 'No records' : fmt(r[key], 2)}',
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 2),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      Expanded(
                        child: Align(
                          alignment: Alignment.bottomCenter,
                          child: FractionallySizedBox(
                            widthFactor: .72,
                            child: Container(
                              height: max(
                                r['records'] == 0 ? 0 : 3,
                                (r[key] as num) / maximum * height,
                              ),
                              decoration: BoxDecoration(
                                color: r['unknown'] == r['records']
                                    ? const Color(0xffb9c7b2)
                                    : green,
                                borderRadius: BorderRadius.circular(6),
                              ),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        (r['date'] as String).substring(8),
                        style: const TextStyle(fontSize: 10),
                      ),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget insights() {
    final o = overview;
    if (o == null) return const Text('Connect to load your footprint.');
    final resources = o['resources'] as Json;
    final index = o['green_index']['value'] as num?;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'The bigger picture',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 24),
        panel(
          Column(
            children: [
              const Text('GREEN INDEX'),
              const SizedBox(height: 16),
              SizedBox(
                height: 130,
                width: 260,
                child: CustomPaint(painter: IndexPainter(index?.toDouble())),
              ),
              Text(
                index == null
                    ? 'Index not defined yet'
                    : '+${index.toStringAsFixed(2)} · demo score',
              ),
            ],
          ),
        ),
        panel(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${fmt(o['total_kg'], 2)} kg CO₂e',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 16),
              ...((o['categories'] as List).cast<Json>().where(
                (c) => (c['co2e_kg'] as num) > 0,
              )).map(
                (c) => Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: Column(
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(c['category'] as String),
                          Text('${fmt(c['co2e_kg'], 2)} kg'),
                        ],
                      ),
                      const SizedBox(height: 6),
                      LinearProgressIndicator(
                        value:
                            (c['co2e_kg'] as num) /
                            max(.001, (o['total_kg'] as num).toDouble()),
                        minHeight: 7,
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ],
                  ),
                ),
              ),
              Text(
                '${o['coverage']['known']} estimated · ${o['coverage']['unknown']} unknown · ${o['coverage']['undated']} undated',
              ),
            ],
          ),
        ),
        panel(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'DAY BY DAY',
                style: TextStyle(letterSpacing: 1.5, fontSize: 11),
              ),
              DropdownButton<String>(
                value: metric,
                isExpanded: true,
                underline: const SizedBox(),
                items: const [
                  DropdownMenuItem(
                    value: 'co2e_kg',
                    child: Text('Carbon · kg CO₂e'),
                  ),
                  DropdownMenuItem(value: 'water_l', child: Text('Water · L')),
                  DropdownMenuItem(
                    value: 'electricity_kwh',
                    child: Text('Electricity · kWh'),
                  ),
                  DropdownMenuItem(
                    value: 'transport_km',
                    child: Text('Travel · km'),
                  ),
                ],
                onChanged: (v) => setState(() => metric = v!),
              ),
              chart(metric),
              const SizedBox(height: 12),
              const Text(
                'A blank day means no records, rather than measured zero use.',
              ),
            ],
          ),
        ),
        panel(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Your resources',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 16),
              Text(
                '${fmt(resources['water_l'])} L water\n${fmt(resources['electricity_kwh'], 2)} kWh electricity\n${fmt(resources['transport_km'])} km travel',
              ),
              const SizedBox(height: 12),
              const Text('Household quantities use your allocated share.'),
            ],
          ),
        ),
      ],
    );
  }

  Widget profile() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text('Your space', style: Theme.of(context).textTheme.headlineMedium),
      const SizedBox(height: 24),
      panel(
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.account_circle_outlined, size: 42, color: green),
            const SizedBox(height: 12),
            Text(
              api.connected
                  ? (api.account?['name'] as String? ?? 'Connected account')
                  : 'Explore LiveGreen',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(
              api.connected
                  ? 'Changes save to your account. Your key is stored in Android secure storage.'
                  : 'Public demo is read-only. Connect your activity key to log and correct records.',
            ),
            const SizedBox(height: 20),
            TextField(
              controller: server,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Server address'),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: keyField,
              obscureText: true,
              enableSuggestions: false,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: 'Activity account key',
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: connecting || loading ? null : connect,
              child: Text(connecting ? 'Connecting…' : 'Connect account'),
            ),
            if (api.connected)
              TextButton(
                onPressed: connecting
                    ? null
                    : () async {
                        requestId++;
                        await api.disconnect();
                        if (!mounted) return;
                        setState(() {
                          overview = null;
                          events = [];
                          factors = [];
                          synced = null;
                          server.text = api.base;
                        });
                        await refresh();
                      },
                child: const Text('Disconnect and remove saved key'),
              ),
          ],
        ),
      ),
      panel(
        const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Capture with care',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
            SizedBox(height: 8),
            Text(
              'Receipt recognition runs on your phone. Only the details you review and save are sent to your server. Activity keys cannot access research sensors or administer the website.',
            ),
          ],
        ),
      ),
    ],
  );

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Row(
        children: [
          SizedBox(
            width: 30,
            height: 30,
            child: CustomPaint(painter: LogoPainter()),
          ),
          SizedBox(width: 10),
          Text('LiveGreen', style: TextStyle(fontWeight: FontWeight.w600)),
        ],
      ),
      actions: [
        IconButton(
          tooltip: 'Refresh',
          onPressed: loading ? null : refresh,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: SafeArea(
      child: RefreshIndicator(
        onRefresh: refresh,
        child: ListView(
          key: ValueKey(tab),
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(22, 0, 22, 32),
          children: [
            if (tab != 3) range(),
            if (loading) const LinearProgressIndicator(),
            if (error != null)
              panel(
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Connection needs attention',
                      style: TextStyle(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 8),
                    Text(error!),
                    Wrap(
                      spacing: 8,
                      children: [
                        TextButton(
                          onPressed: refresh,
                          child: const Text('Retry'),
                        ),
                        TextButton(
                          onPressed: () => setState(() => tab = 3),
                          child: const Text('Connection settings'),
                        ),
                      ],
                    ),
                  ],
                ),
                color: const Color(0xffffeddd),
              ),
            if (overview?['account']['is_demo'] == true && tab != 3)
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: Text(
                  api.connected
                      ? 'Demo account · saved activities'
                      : 'Read-only demo · connect in You to save',
                  style: const TextStyle(fontSize: 12, color: green),
                ),
              ),
            if (!loading || overview != null || tab == 3)
              switch (tab) {
                0 => home(),
                1 => activities(),
                2 => insights(),
                _ => profile(),
              },
            if (synced != null && tab != 3)
              Padding(
                padding: const EdgeInsets.only(top: 20),
                child: Text(
                  'Last loaded ${TimeOfDay.fromDateTime(synced!).format(context)}${error != null ? ' · showing previous data' : ''}',
                  style: const TextStyle(fontSize: 11),
                ),
              ),
          ],
        ),
      ),
    ),
    bottomNavigationBar: NavigationBar(
      selectedIndex: tab,
      onDestinationSelected: (v) => setState(() => tab = v),
      destinations: const [
        NavigationDestination(icon: Icon(Icons.spa_outlined), label: 'Home'),
        NavigationDestination(
          icon: Icon(Icons.receipt_long_outlined),
          label: 'Activities',
        ),
        NavigationDestination(
          icon: Icon(Icons.insights_outlined),
          label: 'Footprint',
        ),
        NavigationDestination(icon: Icon(Icons.person_outline), label: 'You'),
      ],
    ),
  );
}

class LogoPainter extends CustomPainter {
  const LogoPainter();
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 48, size.height / 48);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        const Rect.fromLTWH(0, 0, 48, 48),
        const Radius.circular(14),
      ),
      Paint()..color = green,
    );
    final paint = Paint()
      ..color = Colors.white
      ..strokeWidth = 4
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;
    for (final y in [20.0, 30.0]) {
      canvas.drawPath(
        Path()
          ..moveTo(10, y)
          ..cubicTo(18, y - 12, 30, y + 12, 38, y),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant LogoPainter oldDelegate) => false;
}

class IndexPainter extends CustomPainter {
  final double? value;
  IndexPainter(this.value);
  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height - 20);
    final radius = min(size.width / 2 - 20, size.height - 35);
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      pi,
      pi,
      false,
      Paint()
        ..color = const Color(0xffdce8d8)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 14
        ..strokeCap = StrokeCap.round,
    );
    for (final entry in [(-1.0, '-1'), (0.0, '0'), (1.0, '+1')]) {
      final a = pi + (entry.$1 + 1) / 2 * pi;
      final p = center + Offset(cos(a), sin(a)) * (radius + 18);
      final text = TextPainter(
        text: TextSpan(
          text: entry.$2,
          style: const TextStyle(color: ink, fontSize: 11),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      text.paint(canvas, p - Offset(text.width / 2, text.height / 2));
    }
    if (value != null) {
      final a = pi + (value!.clamp(-1, 1) + 1) / 2 * pi;
      canvas.drawLine(
        center,
        center + Offset(cos(a), sin(a)) * (radius - 8),
        Paint()
          ..color = green
          ..strokeWidth = 4
          ..strokeCap = StrokeCap.round,
      );
    }
    canvas.drawCircle(center, 6, Paint()..color = green);
  }

  @override
  bool shouldRepaint(covariant IndexPainter oldDelegate) =>
      value != oldDelegate.value;
}
