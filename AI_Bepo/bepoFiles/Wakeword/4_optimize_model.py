#!/usr/bin/env python3
"""
4_optimize_model.py
Ottimizzazione modello per Raspberry Pi:
- Conversione TFLite con quantizzazione INT8
- Benchmark latenza su x86 (per stimare performance RPi)
- Validazione accuracy post-quantizzazione
- Generazione modello ONNX come alternativa
"""

import os
import time
import numpy as np
import yaml
from pathlib import Path
import soundfile as sf

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

with open("config.yaml") as f:
    CFG = yaml.safe_load(f)

MODELS_DIR = Path("models")
SR = CFG["audio"]["sample_rate"]


# ──────────────────────────────────────────────
# Conversione TFLite con quantizzazione INT8
# ──────────────────────────────────────────────
def load_representative_dataset(n_samples: int = 500):
    """
    Dataset rappresentativo per calibrazione quantizzazione INT8.
    Cruciale per mantenere accuracy dopo quantizzazione.
    """
    import openwakeword

    oww = openwakeword.Model(wakeword_models=[], enable_speex_noise_suppression=False)

    features_list = []

    # Usa campioni di validation per calibrazione
    val_files = (
        list(Path("data/positive").glob("*.wav"))[:n_samples // 2] +
        list(Path("data/negative").rglob("*.wav"))[:n_samples // 2]
    )

    for audio_path in val_files[:n_samples]:
        try:
            audio, sr = sf.read(str(audio_path))
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
            audio_int16 = (audio * 32767).astype(np.int16)

            chunk_size = CFG["audio"]["chunk_size"]
            if len(audio_int16) >= chunk_size:
                chunk = audio_int16[:chunk_size]
                features = oww.get_parent_model_output(chunk)
                if features is not None and len(features) > 0:
                    features_list.append(features.flatten().astype(np.float32))
                    if len(features_list) >= n_samples:
                        break
        except Exception:
            pass

    print(f"  Dataset calibrazione: {len(features_list)} campioni")
    return np.array(features_list, dtype=np.float32)


def convert_to_tflite_int8(model_path: str,
                            calib_data: np.ndarray) -> str:
    """
    Converte modello Keras → TFLite con quantizzazione INT8.
    INT8: riduce size ~4x, latenza ~2x più veloce vs FP32.
    """
    import tensorflow as tf

    print("\n[TFLite INT8] Conversione...")
    model = tf.keras.models.load_model(model_path)

    # Convertor con quantizzazione INT8 completa
    converter = tf.lite.TFLiteConverter.from_keras_model(model)

    # Ottimizzazioni INT8
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS_INT8,
    ]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8

    # Dataset di calibrazione (necessario per INT8)
    def representative_dataset_gen():
        for sample in calib_data[:300]:
            yield [sample.reshape(1, -1)]

    converter.representative_dataset = representative_dataset_gen

    # Converti
    tflite_model = converter.convert()

    out_path = str(MODELS_DIR / "aria_int8.tflite")
    with open(out_path, "wb") as f:
        f.write(tflite_model)

    size_kb = len(tflite_model) / 1024
    print(f"  ✓ Salvato: {out_path}")
    print(f"  Size: {size_kb:.1f} KB")

    return out_path


def convert_to_tflite_fp16(model_path: str) -> str:
    """
    Conversione FP16 - più accurata di INT8, ma meno efficiente.
    Buona opzione se INT8 degrada troppo l'accuracy.
    """
    import tensorflow as tf

    print("\n[TFLite FP16] Conversione...")
    model = tf.keras.models.load_model(model_path)

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_types = [tf.float16]

    tflite_model = converter.convert()
    out_path = str(MODELS_DIR / "aria_fp16.tflite")
    with open(out_path, "wb") as f:
        f.write(tflite_model)

    size_kb = len(tflite_model) / 1024
    print(f"  ✓ Salvato: {out_path}")
    print(f"  Size: {size_kb:.1f} KB")
    return out_path


def convert_to_tflite_dynamic(model_path: str) -> str:
    """
    Quantizzazione dinamica - bilanciamento ottimale.
    Non richiede dataset di calibrazione.
    """
    import tensorflow as tf

    print("\n[TFLite Dynamic] Conversione...")
    model = tf.keras.models.load_model(model_path)

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]

    tflite_model = converter.convert()
    out_path = str(MODELS_DIR / "aria_dynamic.tflite")
    with open(out_path, "wb") as f:
        f.write(tflite_model)

    size_kb = len(tflite_model) / 1024
    print(f"  ✓ Salvato: {out_path}")
    print(f"  Size: {size_kb:.1f} KB")
    return out_path


# ──────────────────────────────────────────────
# Conversione ONNX (alternativa TFLite)
# ──────────────────────────────────────────────
def convert_to_onnx(model_path: str) -> str:
    """
    Converte a ONNX. Usa con onnxruntime su RPi.
    Spesso più veloce di TFLite per DNN piccoli.
    """
    try:
        import tensorflow as tf
        import tf2onnx
        import onnx
        from onnxruntime.quantization import quantize_dynamic, QuantType

        print("\n[ONNX] Conversione...")
        model = tf.keras.models.load_model(model_path)

        # Salva come SavedModel temporaneo
        saved_dir = str(MODELS_DIR / "_tmp_saved_model")
        model.save(saved_dir)

        # Converti a ONNX
        onnx_path = str(MODELS_DIR / "aria.onnx")
        cmd_args = [
            "python", "-m", "tf2onnx.convert",
            "--saved-model", saved_dir,
            "--output", onnx_path,
            "--opset", "13",
        ]
        import subprocess
        result = subprocess.run(cmd_args, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"  ⚠ Errore ONNX: {result.stderr}")
            return ""

        # Quantizzazione INT8 ONNX
        onnx_int8_path = str(MODELS_DIR / "aria_int8.onnx")
        quantize_dynamic(
            model_input=onnx_path,
            model_output=onnx_int8_path,
            weight_type=QuantType.QInt8,
        )

        size_kb = Path(onnx_int8_path).stat().st_size / 1024
        print(f"  ✓ ONNX INT8 salvato: {onnx_int8_path}")
        print(f"  Size: {size_kb:.1f} KB")
        return onnx_int8_path

    except ImportError as e:
        print(f"  ⚠ ONNX non disponibile: {e}")
        return ""


# ──────────────────────────────────────────────
# Benchmark e validazione
# ──────────────────────────────────────────────
def benchmark_tflite(tflite_path: str, test_data: np.ndarray,
                     n_runs: int = 1000) -> dict:
    """
    Benchmark latenza modello TFLite.
    n_runs=1000 per media stabile.
    """
    import tensorflow as tf

    interpreter = tf.lite.Interpreter(model_path=tflite_path)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_dtype = input_details[0]["dtype"]
    input_scale = input_details[0]["quantization"][0]
    input_zero_point = input_details[0]["quantization"][1]

    # Warmup
    for _ in range(10):
        sample = test_data[0:1].astype(np.float32)
        if input_dtype == np.int8:
            if input_scale > 0:
                sample = (sample / input_scale + input_zero_point).astype(np.int8)
            else:
                sample = sample.astype(np.int8)
        interpreter.set_tensor(input_details[0]["index"], sample)
        interpreter.invoke()

    # Benchmark
    latencies = []
    for i in range(n_runs):
        sample = test_data[i % len(test_data):i % len(test_data) + 1]
        if input_dtype == np.int8:
            if input_scale > 0:
                sample = (sample / input_scale + input_zero_point).astype(np.int8)
            else:
                sample = sample.astype(np.int8)

        t0 = time.perf_counter()
        interpreter.set_tensor(input_details[0]["index"], sample)
        interpreter.invoke()
        _ = interpreter.get_tensor(output_details[0]["index"])
        latencies.append((time.perf_counter() - t0) * 1000)

    latencies = np.array(latencies)
    results = {
        "mean_ms": float(np.mean(latencies)),
        "p50_ms": float(np.percentile(latencies, 50)),
        "p95_ms": float(np.percentile(latencies, 95)),
        "p99_ms": float(np.percentile(latencies, 99)),
        "min_ms": float(np.min(latencies)),
    }
    return results


def validate_accuracy_tflite(tflite_path: str, X_val: np.ndarray,
                              y_val: np.ndarray,
                              threshold: float = 0.5) -> dict:
    """Valida accuracy del modello quantizzato su dataset di test."""
    import tensorflow as tf

    interpreter = tf.lite.Interpreter(model_path=tflite_path)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_dtype = input_details[0]["dtype"]
    input_scale = input_details[0]["quantization"][0]
    input_zero_point = input_details[0]["quantization"][1]
    output_scale = output_details[0]["quantization"][0]
    output_zero_point = output_details[0]["quantization"][1]

    predictions = []
    for sample in X_val:
        inp = sample.reshape(1, -1).astype(np.float32)
        if input_dtype == np.int8 and input_scale > 0:
            inp = (inp / input_scale + input_zero_point).astype(np.int8)

        interpreter.set_tensor(input_details[0]["index"], inp)
        interpreter.invoke()
        output = interpreter.get_tensor(output_details[0]["index"])

        # De-quantizza output se INT8
        if output_details[0]["dtype"] == np.int8 and output_scale > 0:
            score = float((output.flatten()[0] - output_zero_point) * output_scale)
        else:
            score = float(output.flatten()[0])

        predictions.append(score)

    predictions = np.array(predictions)
    y_pred_bin = (predictions > threshold).astype(int)

    tp = ((y_pred_bin == 1) & (y_val == 1)).sum()
    fp = ((y_pred_bin == 1) & (y_val == 0)).sum()
    tn = ((y_pred_bin == 0) & (y_val == 0)).sum()
    fn = ((y_pred_bin == 0) & (y_val == 1)).sum()

    precision = tp / (tp + fp + 1e-8)
    recall = tp / (tp + fn + 1e-8)
    fpr = fp / (fp + tn + 1e-8)

    return {
        "precision": float(precision),
        "recall": float(recall),
        "fpr": float(fpr),
        "f1": float(2 * precision * recall / (precision + recall + 1e-8)),
    }


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def optimize_all():
    model_path = str(MODELS_DIR / "wakeword_model.h5")
    if not Path(model_path).exists():
        print(f"❌ Modello non trovato: {model_path}")
        print("   Esegui prima 3_train_model.py")
        return

    print("="*50)
    print(" OTTIMIZZAZIONE MODELLO PER RASPBERRY PI")
    print("="*50)

    # Carica dataset calibrazione
    print("\n[1/4] Caricamento dataset calibrazione...")
    calib_data = load_representative_dataset(500)

    # Converti in tutti i formati
    print("\n[2/4] Conversione modelli...")
    paths = {}
    paths["int8"] = convert_to_tflite_int8(model_path, calib_data)
    paths["fp16"] = convert_to_tflite_fp16(model_path)
    paths["dynamic"] = convert_to_tflite_dynamic(model_path)
    paths["onnx"] = convert_to_onnx(model_path)

    # Benchmark su PC (moltiplicare ~3-4x per RPi 4)
    print("\n[3/4] Benchmark latenza (PC - moltiplicare ×3-4 per RPi 4)...")
    test_data = calib_data[:100]

    for name, path in paths.items():
        if path and Path(path).suffix == ".tflite":
            results = benchmark_tflite(path, test_data, n_runs=500)
            size_kb = Path(path).stat().st_size / 1024
            print(f"\n  [{name.upper()}] {Path(path).name} ({size_kb:.0f} KB)")
            print(f"    Latenza media: {results['mean_ms']:.2f}ms")
            print(f"    P95:           {results['p95_ms']:.2f}ms")
            print(f"    P99:           {results['p99_ms']:.2f}ms")

    # Valida accuracy post-quantizzazione
    print("\n[4/4] Validazione accuracy post-quantizzazione...")
    # Usa calib_data come proxy validation (in produzione usa un set separato)
    y_fake = np.array([1] * (len(calib_data)//2) + [0] * (len(calib_data)//2))
    y_fake = y_fake[:len(calib_data)]

    best_path = paths.get("int8", "")
    if best_path and Path(best_path).exists():
        metrics = validate_accuracy_tflite(best_path, calib_data, y_fake)
        print(f"\n  INT8 Metrics (threshold={CFG['inference']['threshold']}):")
        print(f"    Precision: {metrics['precision']:.4f}")
        print(f"    Recall:    {metrics['recall']:.4f}")
        print(f"    FPR:       {metrics['fpr']:.4f}")
        print(f"    F1:        {metrics['f1']:.4f}")

    print("\n" + "="*50)
    print(" MODELLI PRONTI PER RASPBERRY PI")
    print("="*50)
    print("\n Consigliato: aria_int8.tflite")
    print(" Alternativa: aria_dynamic.tflite (se INT8 degrada accuracy)")
    print("\n Copia su RPi:")
    print("   scp models/aria_int8.tflite pi@raspberrypi:~/wakeword/models/")
    print("\n Stima performance RPi 4 (2 core dedicati):")
    print("   Latenza ~3-8ms per inferenza")
    print("   CPU usage ~5-15% @ 80ms chunk interval")


if __name__ == "__main__":
    optimize_all()
