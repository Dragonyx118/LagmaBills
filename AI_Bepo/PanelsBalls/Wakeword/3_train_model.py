#!/usr/bin/env python3
"""
3_train_model.py
Training del modello wake word con openWakeWord.

Architettura:
- Backbone: features estratte da modello audio pre-trained (melspectrogram + embedding)
- Head: DNN leggero [128 → 64 → 32 → 1] con dropout
- Loss: BCE con class weights per dataset sbilanciato
- Target: ~200KB modello finale
"""

import os
import numpy as np
import yaml
from pathlib import Path
from tqdm import tqdm
import random
import soundfile as sf
import matplotlib.pyplot as plt

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"  # Silenzia log TF

with open("config.yaml") as f:
    CFG = yaml.safe_load(f)

SR = CFG["audio"]["sample_rate"]
MODELS_DIR = Path("models")
MODELS_DIR.mkdir(exist_ok=True)


# ──────────────────────────────────────────────
# Feature extraction con openWakeWord
# ──────────────────────────────────────────────
def extract_features_batch(audio_files: list[str],
                            openwakeword_model) -> np.ndarray:
    """
    Estrae embeddings audio usando il backbone pre-trained di openWakeWord.
    Il backbone converte mel-spectrogram in vettori 96-dim.
    """
    all_features = []

    for audio_path in tqdm(audio_files, desc="Feature extraction", leave=False):
        try:
            audio, sr = sf.read(audio_path)
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)

            # Converti a int16 (formato atteso da openWakeWord)
            audio_int16 = (audio * 32767).astype(np.int16)

            # Segmenta in chunk da 1280 campioni (80ms @ 16kHz)
            chunk_size = CFG["audio"]["chunk_size"]
            chunks = []
            for i in range(0, len(audio_int16) - chunk_size, chunk_size // 2):
                chunk = audio_int16[i:i + chunk_size]
                if len(chunk) == chunk_size:
                    chunks.append(chunk)

            if not chunks:
                continue

            # Estrai features per ogni chunk
            for chunk in chunks:
                features = openwakeword_model.get_parent_model_output(chunk)
                if features is not None and len(features) > 0:
                    all_features.append(features.flatten())

        except Exception as e:
            pass  # Skip file corrotti

    return np.array(all_features, dtype=np.float32) if all_features else np.empty((0, 96))


# ──────────────────────────────────────────────
# Caricamento dataset
# ──────────────────────────────────────────────
def load_dataset():
    """Carica e bilancia dataset positivi e negativi."""
    print("Caricamento dataset...")

    # Positivi: originali + augmentati
    pos_files = (
        sorted(Path("data/positive").glob("*.wav")) +
        sorted(Path("data/augmented").glob("*.wav"))
    )

    # Negativi: tutti i file disponibili
    neg_dirs = [
        Path("data/negative/common_voice_it"),
        Path("data/negative/librispeech"),
        Path("data/negative/musan"),
        Path("data/negative/hard_negatives"),
    ]
    neg_files = []
    for d in neg_dirs:
        if d.exists():
            neg_files.extend(list(d.rglob("*.wav")))
            neg_files.extend(list(d.rglob("*.flac")))

    print(f"  Positivi: {len(pos_files):,}")
    print(f"  Negativi: {len(neg_files):,}")

    # Bilancio: max 5:1 negativi/positivi
    if len(neg_files) > len(pos_files) * 5:
        random.shuffle(neg_files)
        neg_files = neg_files[:len(pos_files) * 5]
        print(f"  Negativi (bilanciati): {len(neg_files):,}")

    return [str(f) for f in pos_files], [str(f) for f in neg_files]


# ──────────────────────────────────────────────
# Modello DNN leggero
# ──────────────────────────────────────────────
def build_lightweight_model(input_dim: int = 96) -> "tf.keras.Model":
    """
    DNN leggero ottimizzato per CPU embedded.

    Architettura [input_dim → 128 → 64 → 32 → 1]:
    - Totale parametri: ~15.000
    - Size stimata: ~180KB (FP32), ~60KB (INT8)
    - Latenza stimata: <5ms su RPi 4
    """
    import tensorflow as tf

    model = tf.keras.Sequential([
        # Input
        tf.keras.layers.Input(shape=(input_dim,), name="embedding_input"),

        # Layer 1: 128 unità
        tf.keras.layers.Dense(128, name="dense_1"),
        tf.keras.layers.BatchNormalization(name="bn_1"),
        tf.keras.layers.Activation("relu", name="relu_1"),
        tf.keras.layers.Dropout(0.3, name="dropout_1"),

        # Layer 2: 64 unità
        tf.keras.layers.Dense(64, name="dense_2"),
        tf.keras.layers.BatchNormalization(name="bn_2"),
        tf.keras.layers.Activation("relu", name="relu_2"),
        tf.keras.layers.Dropout(0.2, name="dropout_2"),

        # Layer 3: 32 unità
        tf.keras.layers.Dense(32, name="dense_3"),
        tf.keras.layers.Activation("relu", name="relu_3"),

        # Output: probabilità wake word
        tf.keras.layers.Dense(1, activation="sigmoid", name="output"),
    ], name="wakeword_dnn")

    return model


def train_model():
    """Pipeline completa di training."""
    import tensorflow as tf
    import openwakeword

    print("\n" + "="*50)
    print(" TRAINING WAKE WORD MODEL")
    print("="*50)

    # 1. Carica openWakeWord per feature extraction
    print("\n[1/6] Caricamento backbone openWakeWord...")
    oww = openwakeword.Model(
        wakeword_models=[],
        enable_speex_noise_suppression=False,
    )

    # 2. Carica dataset
    print("[2/6] Caricamento file audio...")
    pos_files, neg_files = load_dataset()

    # 3. Estrai features
    print("[3/6] Estrazione features...")
    print("  Feature extraction positivi...")
    X_pos = extract_features_batch(pos_files, oww)
    y_pos = np.ones(len(X_pos), dtype=np.float32)

    print("  Feature extraction negativi...")
    X_neg = extract_features_batch(neg_files, oww)
    y_neg = np.zeros(len(X_neg), dtype=np.float32)

    print(f"  Feature shapes: positivi={X_pos.shape}, negativi={X_neg.shape}")

    if len(X_pos) == 0 or len(X_neg) == 0:
        print("❌ Dataset vuoto! Verifica i file audio.")
        return

    # 4. Combina e shuffle
    X = np.vstack([X_pos, X_neg])
    y = np.concatenate([y_pos, y_neg])
    indices = np.random.permutation(len(X))
    X, y = X[indices], y[indices]

    # Split train/val
    val_size = int(len(X) * CFG["training"]["val_split"])
    X_train, X_val = X[val_size:], X[:val_size]
    y_train, y_val = y[val_size:], y[:val_size]

    print(f"\n  Train: {len(X_train):,} | Val: {len(X_val):,}")
    print(f"  Positivi train: {y_train.sum():.0f} ({y_train.mean()*100:.1f}%)")

    # 5. Build e compila modello
    print("\n[4/6] Build modello...")
    input_dim = X.shape[1] if X.ndim > 1 else 96
    model = build_lightweight_model(input_dim)
    model.summary()

    # Class weights per dataset sbilanciato
    pos_weight = CFG["training"]["positive_weight"]
    class_weight = {0: 1.0, 1: pos_weight}

    model.compile(
        optimizer=tf.keras.optimizers.Adam(
            learning_rate=CFG["training"]["learning_rate"]
        ),
        loss=tf.keras.losses.BinaryCrossentropy(label_smoothing=0.05),
        metrics=[
            tf.keras.metrics.BinaryAccuracy(name="accuracy"),
            tf.keras.metrics.AUC(name="auc"),
            tf.keras.metrics.Precision(name="precision"),
            tf.keras.metrics.Recall(name="recall"),
        ],
    )

    # 6. Training con callbacks
    print("\n[5/6] Training...")
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_auc",
            patience=CFG["training"]["early_stopping_patience"],
            mode="max",
            restore_best_weights=True,
            verbose=1,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=5,
            min_lr=1e-6,
            verbose=1,
        ),
        tf.keras.callbacks.ModelCheckpoint(
            filepath=str(MODELS_DIR / "best_model.h5"),
            monitor="val_auc",
            mode="max",
            save_best_only=True,
            verbose=0,
        ),
        tf.keras.callbacks.CSVLogger(
            str(MODELS_DIR / "training_log.csv")
        ),
    ]

    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        batch_size=CFG["training"]["batch_size"],
        epochs=CFG["training"]["epochs"],
        class_weight=class_weight,
        callbacks=callbacks,
        verbose=1,
    )

    # 7. Valutazione finale
    print("\n[6/6] Valutazione...")
    results = model.evaluate(X_val, y_val, verbose=0)
    metrics = dict(zip(model.metrics_names, results))
    print(f"  Accuracy: {metrics['accuracy']:.4f}")
    print(f"  AUC:      {metrics['auc']:.4f}")
    print(f"  Precision:{metrics['precision']:.4f}")
    print(f"  Recall:   {metrics['recall']:.4f}")

    # Calcola False Positive Rate
    y_pred = model.predict(X_val, verbose=0).flatten()
    y_pred_bin = (y_pred > 0.5).astype(int)
    neg_mask = y_val == 0
    fpr = (y_pred_bin[neg_mask] == 1).mean()
    print(f"  FPR @0.5: {fpr:.4f} ({fpr*100:.2f}%)")

    # Trova threshold ottimale
    _find_optimal_threshold(y_val, y_pred)

    # Salva modello
    model.save(str(MODELS_DIR / "wakeword_model.h5"))
    print(f"\n✓ Modello salvato in {MODELS_DIR}/wakeword_model.h5")

    # Plot training
    _plot_training_history(history)

    return model


def _find_optimal_threshold(y_true: np.ndarray, y_pred: np.ndarray):
    """Trova soglia ottimale per bilanciare precision/recall."""
    from sklearn.metrics import precision_recall_curve, f1_score

    precision, recall, thresholds = precision_recall_curve(y_true, y_pred)

    # F1 score per ogni threshold
    f1_scores = 2 * (precision * recall) / (precision + recall + 1e-8)
    best_idx = np.argmax(f1_scores)
    best_threshold = thresholds[best_idx] if best_idx < len(thresholds) else 0.5

    print(f"\n  Threshold ottimale (max F1): {best_threshold:.3f}")
    print(f"  F1 score: {f1_scores[best_idx]:.4f}")
    print(f"  Precision: {precision[best_idx]:.4f}")
    print(f"  Recall: {recall[best_idx]:.4f}")

    # Threshold conservativo (meno falsi positivi)
    # Cerca threshold con FPR < 1%
    neg_count = (y_true == 0).sum()
    for thresh in np.arange(0.9, 0.4, -0.01):
        fp = ((y_pred > thresh) & (y_true == 0)).sum()
        fpr = fp / (neg_count + 1e-8)
        if fpr < 0.01:
            print(f"  Threshold conservativo (FPR<1%): {thresh:.2f}")
            break

    # Aggiorna config
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["inference"]["threshold"] = round(float(best_threshold), 2)
    with open("config.yaml", "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)
    print(f"  ✓ Threshold aggiornato in config.yaml: {best_threshold:.2f}")


def _plot_training_history(history):
    """Salva grafici di training."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    axes[0, 0].plot(history.history["loss"], label="Train")
    axes[0, 0].plot(history.history["val_loss"], label="Val")
    axes[0, 0].set_title("Loss")
    axes[0, 0].legend()

    axes[0, 1].plot(history.history["auc"], label="Train")
    axes[0, 1].plot(history.history["val_auc"], label="Val")
    axes[0, 1].set_title("AUC")
    axes[0, 1].legend()

    axes[1, 0].plot(history.history["precision"], label="Precision")
    axes[1, 0].plot(history.history["recall"], label="Recall")
    axes[1, 0].set_title("Precision / Recall")
    axes[1, 0].legend()

    axes[1, 1].plot(history.history["accuracy"], label="Train")
    axes[1, 1].plot(history.history["val_accuracy"], label="Val")
    axes[1, 1].set_title("Accuracy")
    axes[1, 1].legend()

    plt.tight_layout()
    plt.savefig(str(MODELS_DIR / "training_curves.png"), dpi=150)
    plt.close()
    print(f"  Plot salvato: {MODELS_DIR}/training_curves.png")


if __name__ == "__main__":
    train_model()
