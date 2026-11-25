import 'dart:math';

import 'package:material_ui/material_ui.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';

class ActivityEditor extends StatefulWidget {
  final LiveGreenApi api;
  final List<Json> factors;
  final String kind;
  final Json? original;
  final XFile? recovered;
  const ActivityEditor({
    super.key,
    required this.api,
    required this.factors,
    required this.kind,
    this.original,
    this.recovered,
  });
  @override
  State<ActivityEditor> createState() => _ActivityEditorState();
}

class _ActivityEditorState extends State<ActivityEditor> {
  final form = GlobalKey<FormState>();
  final name = TextEditingController();
  final quantity = TextEditingController();
  final spend = TextEditingController();
  final receipt = TextEditingController();
  final itemName = TextEditingController();
  final itemQuantity = TextEditingController();
  final share = TextEditingController(text: '1');
  late String category, status, eventId, unit;
  String? factorId, itemFactorId;
  String itemUnit = 'item';
  List<Json> items = [];
  DateTime? occurred;
  bool busy = false, scanning = false;
  String? error;
  String inputMethod = 'manual';
  bool timeEdited = false;
  String mode = '';

  @override
  void initState() {
    super.initState();
    final r = widget.original;
    category =
        r?['category'] as String? ??
        (widget.kind == 'transport'
            ? 'transport'
            : widget.kind == 'household'
            ? 'water'
            : 'shopping');
    unit =
        r?['unit'] as String? ??
        (category == 'transport'
            ? 'passenger_km'
            : category == 'water'
            ? 'litre'
            : 'item');
    status = r?['status'] as String? ?? 'needs_review';
    eventId =
        r?['id'] as String? ??
        'mobile-${DateTime.now().microsecondsSinceEpoch}-${Random.secure().nextInt(1 << 32)}';
    name.text = r?['name'] as String? ?? '';
    quantity.text = r?['quantity']?.toString() ?? '';
    spend.text = r?['amount_minor'] == null
        ? ''
        : ((r!['amount_minor'] as num) / 100).toStringAsFixed(2);
    share.text = (r?['share'] ?? 1).toString();
    factorId = r?['factor_id'] as String?;
    occurred = r?['occurred_at'] == null
        ? null
        : DateTime.parse(r!['occurred_at'] as String)
              .toUtc()
              .add(const Duration(hours: 8));
    items = ((r?['items'] ?? []) as List)
        .map((v) => Map<String, dynamic>.from(v as Map))
        .toList();
    receipt.text = (r?['metadata'] as Json?)?['receipt_text'] as String? ?? '';
    mode = (r?['metadata'] as Json?)?['mode'] as String? ?? '';
    inputMethod =
        (r?['metadata'] as Json?)?['input_method'] as String? ?? 'manual';
    if (widget.recovered != null) {
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => recognize(widget.recovered!),
      );
    }
  }

  @override
  void dispose() {
    for (final c in [
      name,
      quantity,
      spend,
      receipt,
      itemName,
      itemQuantity,
      share,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> recognize(XFile image) async {
    setState(() {
      scanning = true;
      error = null;
    });
    final recognizer = TextRecognizer(script: TextRecognitionScript.chinese);
    try {
      final result = await recognizer.processImage(
        InputImage.fromFilePath(image.path),
      );
      if (!mounted) return;
      receipt.text = result.text;
      inputMethod = 'on_device_ocr';
      if (result.text.trim().isEmpty) {
        setState(
          () => error =
              'No text found. Try a sharper photo or enter the details.',
        );
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => error = 'Could not read this photo. Try another photo or enter the receipt text.',
        );
      }
    } finally {
      await recognizer.close();
      if (mounted) setState(() => scanning = false);
    }
  }

  Future<void> scan(ImageSource source) async {
    try {
      final image = await ImagePicker().pickImage(
        source: source,
        maxWidth: 2400,
        imageQuality: 90,
        requestFullMetadata: false,
      );
      if (image != null && mounted) await recognize(image);
    } catch (_) {
      if (mounted) {
        setState(
          () => error =
              'Photo access unavailable. You can still enter details manually.',
        );
      }
    }
  }

  Future<void> chooseTime() async {
    final now = DateTime.now().toUtc().add(const Duration(hours: 8));
    final initial = occurred ?? now;
    final date = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime(2020),
      lastDate: DateTime(now.year + 1, 12, 31),
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(initial),
    );
    if (time != null && mounted) {
      timeEdited = true;
      setState(
        () => occurred = DateTime(
          date.year,
          date.month,
          date.day,
          time.hour,
          time.minute,
        ),
      );
    }
  }

  String? number(String? v, {bool optional = true, double max = 1e9}) {
    if (v == null || v.trim().isEmpty) {
      return optional ? null : 'Enter a quantity';
    }
    final n = double.tryParse(v);
    return n == null || !n.isFinite || n < 0 || n > max
        ? 'Enter a valid positive number'
        : null;
  }

  List<DropdownMenuItem<String>> factorOptions(String forUnit) => [
    const DropdownMenuItem(value: '', child: Text('No matching factor yet')),
    ...widget.factors
        .where(
          (f) =>
              f['unit'] == forUnit &&
              (widget.api.account?['is_demo'] == true ||
                  f['classification'] != 'synthetic'),
        )
        .map(
          (f) => DropdownMenuItem(
            value: f['id'] as String,
            child: Text(
              '${f['id']} · ${f['value']} kg',
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ),
  ];

  void addItem() {
    final n = double.tryParse(itemQuantity.text);
    if (itemName.text.trim().isEmpty ||
        itemName.text.trim().length > 120 ||
        n == null ||
        !n.isFinite ||
        n <= 0 ||
        n > 1e9 ||
        items.length >= 40) {
      setState(
        () => error =
            'Enter an item name and a positive quantity; maximum 40 items.',
      );
      return;
    }
    setState(() {
      items.add({
        'name': itemName.text.trim(),
        'quantity': n,
        'unit': itemUnit,
        'factor_id': itemFactorId,
        'packaging_g': null,
      });
      itemName.clear();
      itemQuantity.clear();
      error = null;
    });
  }

  Future<void> save() async {
    if (!form.currentState!.validate() || scanning) return;
    if (widget.kind == 'shopping' &&
        (itemName.text.trim().isNotEmpty ||
            itemQuantity.text.trim().isNotEmpty)) {
      setState(
        () => error = 'Tap Add item to include the item you entered, or clear its fields.',
      );
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final original = widget.original;
      final metadata = {
        ...?original?['metadata'] as Json?,
        if (widget.kind == 'shopping') 'receipt_text': receipt.text.trim(),
        if (widget.kind == 'shopping') 'input_method': inputMethod,
        if (widget.kind == 'transport') 'mode': mode.isEmpty ? null : mode,
      };
      // Keep an existing journey trace/end only when its start is unchanged.
      final at = widget.original != null && !timeEdited
          ? widget.original!['occurred_at'] as String?
          : occurred == null
          ? null
          : DateTime.utc(
              occurred!.year,
              occurred!.month,
              occurred!.day,
              occurred!.hour,
              occurred!.minute,
            ).subtract(const Duration(hours: 8)).toIso8601String();
      final oldAt = original?['occurred_at'];
      final timeChanged = at == null
          ? oldAt != null
          : oldAt == null ||
                DateTime.parse(at) != DateTime.parse(oldAt as String);
      if (timeChanged) metadata.remove('trace');
      final payload = <String, dynamic>{
        'name': name.text.trim(),
        'kind': widget.kind,
        'category': category,
        'subcategory': original?['subcategory'] ?? 'Manual entry',
        'occurred_at': at,
        'timezone': 'Asia/Hong_Kong',
        if (timeChanged) 'ended_at': null,
        'quantity': widget.kind == 'shopping' || quantity.text.trim().isEmpty
            ? null
            : double.parse(quantity.text),
        'unit': widget.kind == 'shopping' ? null : unit,
        'factor_id': widget.kind == 'shopping' ? null : factorId,
        'share': double.parse(share.text),
        'status': status,
        'scope': widget.kind == 'household' ? 'inside' : 'outside',
        'amount_minor': spend.text.trim().isEmpty
            ? null
            : (double.parse(spend.text) * 100).round(),
        'currency': original?['currency'] ?? 'HKD',
        'items': items,
        'metadata': metadata,
        if (original == null) 'id': eventId,
        if (original == null) 'source_type': 'livegreen-mobile',
      };
      final saved = await widget.api.save(payload, original: original);
      if (mounted) Navigator.pop(context, saved);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Widget field(
    TextEditingController c,
    String label, {
    bool numeric = false,
    bool required = false,
    int lines = 1,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: TextFormField(
      controller: c,
      maxLines: lines,
      maxLength: numeric
          ? 24
          : lines > 1
          ? 12000
          : 120,
      keyboardType: numeric
          ? const TextInputType.numberWithOptions(decimal: true)
          : TextInputType.text,
      decoration: InputDecoration(labelText: label, counterText: ''),
      validator: numeric
          ? (v) => number(v, optional: !required)
          : required
          ? (v) => v == null || v.trim().isEmpty ? 'Enter a name' : null
          : null,
    ),
  );

  @override
  Widget build(BuildContext context) {
    final shopping = widget.kind == 'shopping';
    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.original == null ? 'Log ${widget.kind}' : 'Activity details',
        ),
      ),
      body: AbsorbPointer(
        absorbing: busy,
        child: Form(
          key: form,
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              if (shopping) ...[
                Text(
                  'Keep the receipt. Lose the guesswork.',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  children: [
                    OutlinedButton.icon(
                      onPressed: scanning
                          ? null
                          : () => scan(ImageSource.camera),
                      icon: const Icon(Icons.camera_alt_outlined),
                      label: const Text('Take photo'),
                    ),
                    OutlinedButton.icon(
                      onPressed: scanning
                          ? null
                          : () => scan(ImageSource.gallery),
                      icon: const Icon(Icons.photo_outlined),
                      label: const Text('Choose photo'),
                    ),
                  ],
                ),
                const Text(
                  'Text is recognized on your phone. Review before saving; photos are not uploaded.',
                ),
                if (scanning) const LinearProgressIndicator(),
                const SizedBox(height: 20),
              ],
              field(
                name,
                shopping ? 'Shop or purchase name' : 'Activity name',
                required: true,
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(
                  occurred == null
                      ? 'When did this happen?'
                      : '${occurred!.toIso8601String().substring(0, 16).replaceFirst('T', ' ')} · Hong Kong',
                ),
                subtitle: Text(
                  occurred == null
                      ? 'Unknown until you confirm it'
                      : 'Tap to change',
                ),
                trailing: const Icon(Icons.calendar_today_outlined),
                onTap: chooseTime,
              ),
              if (occurred != null)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: () => setState(() {
                      occurred = null;
                      timeEdited = true;
                    }),
                    child: const Text('Keep time unknown'),
                  ),
                ),
              const SizedBox(height: 16),
              if (widget.kind == 'transport') ...[
                DropdownButtonFormField<String>(
                  initialValue: mode,
                  decoration: const InputDecoration(labelText: 'Travel mode'),
                  items: {mode, '', 'mtr', 'bus', 'car', 'walk', 'bicycle'}
                      .map(
                        (v) => DropdownMenuItem(
                          value: v,
                          child: Text(
                            v.isEmpty ? 'Not confirmed' : v.toUpperCase(),
                          ),
                        ),
                      )
                      .toList(),
                  onChanged: (v) => setState(() => mode = v!),
                ),
                const SizedBox(height: 16),
              ],
              if (widget.kind == 'household') ...[
                DropdownButtonFormField<String>(
                  initialValue: category,
                  decoration: const InputDecoration(labelText: 'Resource'),
                  items: const [
                    DropdownMenuItem(value: 'water', child: Text('Water')),
                    DropdownMenuItem(
                      value: 'energy',
                      child: Text('Electricity'),
                    ),
                  ],
                  onChanged: (v) => setState(() {
                    category = v!;
                    unit = v == 'water' ? 'litre' : 'kwh';
                    factorId = null;
                  }),
                ),
                const SizedBox(height: 16),
              ],
              if (!shopping) ...[
                field(
                  quantity,
                  unit == 'litre'
                      ? 'Litres'
                      : unit == 'kwh'
                      ? 'kWh'
                      : 'Distance · passenger-km',
                  numeric: true,
                ),
                DropdownButtonFormField<String>(
                  key: ValueKey('$unit-$factorId'),
                  initialValue: factorId ?? '',
                  isExpanded: true,
                  decoration: const InputDecoration(
                    labelText: 'Emission factor',
                  ),
                  items: factorOptions(unit),
                  onChanged: (v) =>
                      setState(() => factorId = v == '' ? null : v),
                ),
                const SizedBox(height: 16),
              ],
              if (shopping) ...[
                field(
                  spend,
                  'Total paid · ${widget.original?['currency'] ?? 'HKD'}',
                  numeric: true,
                ),
                ExpansionTile(
                  title: const Text('Receipt text'),
                  initiallyExpanded: receipt.text.isNotEmpty,
                  children: [
                    field(receipt, 'Review recognized text', lines: 6),
                  ],
                ),
                const SizedBox(height: 16),
                Text('Items', style: Theme.of(context).textTheme.titleLarge),
                ...items.asMap().entries.map(
                  (entry) => ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(entry.value['name'] as String),
                    subtitle: Text(
                      '${entry.value['quantity']} ${entry.value['unit']} · ${entry.value['factor_id'] ?? 'factor unknown'}',
                    ),
                    trailing: IconButton(
                      tooltip: 'Remove item',
                      icon: const Icon(Icons.close),
                      onPressed: () =>
                          setState(() => items.removeAt(entry.key)),
                    ),
                  ),
                ),
                field(itemName, 'Item name'),
                field(itemQuantity, 'Item quantity', numeric: true),
                DropdownButtonFormField<String>(
                  initialValue: itemUnit,
                  decoration: const InputDecoration(labelText: 'Item unit'),
                  items: ['item', 'kg', 'litre']
                      .map((u) => DropdownMenuItem(value: u, child: Text(u)))
                      .toList(),
                  onChanged: (v) => setState(() {
                    itemUnit = v!;
                    itemFactorId = null;
                  }),
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<String>(
                  key: ValueKey('item-$itemUnit-$itemFactorId'),
                  initialValue: itemFactorId ?? '',
                  isExpanded: true,
                  decoration: const InputDecoration(
                    labelText: 'Matching item factor',
                  ),
                  items: factorOptions(itemUnit),
                  onChanged: (v) =>
                      setState(() => itemFactorId = v == '' ? null : v),
                ),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: addItem,
                    icon: const Icon(Icons.add),
                    label: const Text('Add item'),
                  ),
                ),
              ],
              TextFormField(
                controller: share,
                decoration: const InputDecoration(
                  labelText: 'Your share · 0–1',
                ),
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                validator: (v) {
                  final n = double.tryParse(v ?? '');
                  return n == null || !n.isFinite || n <= 0 || n > 1
                      ? 'Enter a share above 0 and up to 1'
                      : null;
                },
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                initialValue: status,
                decoration: const InputDecoration(labelText: 'Status'),
                items: const [
                  DropdownMenuItem(
                    value: 'needs_review',
                    child: Text('Needs review'),
                  ),
                  DropdownMenuItem(
                    value: 'confirmed',
                    child: Text('Confirmed'),
                  ),
                  DropdownMenuItem(value: 'excluded', child: Text('Excluded')),
                ],
                onChanged: (v) => setState(() => status = v!),
              ),
              const SizedBox(height: 16),
              const Text(
                'Carbon stays unknown without confirmed quantities and a matching factor.',
              ),
              if (widget.original?['estimate'] != null)
                ExpansionTile(
                  title: const Text('How we estimated this'),
                  children: [
                    Text(widget.original!['estimate']['boundary'] as String),
                    ...((widget.original!['estimate']['terms'] ?? []) as List).map(
                      (t) => ListTile(
                        title: Text(
                          '${t['quantity']} × ${t['factor']['value']} × ${t['share']} = ${t['kg']} kg',
                        ),
                        subtitle: Text(
                          '${t['factor']['source']} · ${t['factor']['classification']}',
                        ),
                      ),
                    ),
                  ],
                ),
              if (error != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Text(
                    error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              const SizedBox(height: 24),
              FilledButton(
                onPressed: busy || scanning ? null : save,
                child: Text(busy ? 'Saving…' : 'Save activity'),
              ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }
}
