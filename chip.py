# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Wudstyz
"""Lecteur de cartes à puce via PC/SC (testé et fiable en lecture/écriture avec un HID OMNIKEY 3121) : ATR, commandes APDU, lecture et écriture mémoire."""
import threading

try:
    from smartcard.ATR import ATR
    from smartcard.CardConnection import CardConnection
    from smartcard.System import readers as pcsc_readers
    from smartcard.Exceptions import CardConnectionException, NoCardException
    AVAILABLE = True
except Exception:  # pyscard absent : l'onglet Puce affichera un message
    AVAILABLE = False


class ChipError(Exception):
    pass


SW_TEXT = {
    0x9000: "Succès",
    0x6283: "Fichier invalidé",
    0x6300: "Vérification échouée",
    0x6700: "Longueur incorrecte",
    0x6881: "Canal logique non supporté",
    0x6982: "Condition de sécurité non satisfaite",
    0x6983: "Méthode d'authentification bloquée",
    0x6985: "Conditions d'utilisation non satisfaites",
    0x6A80: "Données incorrectes",
    0x6A81: "Fonction non supportée",
    0x6A82: "Fichier ou application introuvable",
    0x6A83: "Enregistrement introuvable",
    0x6A86: "Paramètres P1/P2 incorrects",
    0x6A88: "Donnée de référence introuvable",
    0x6B00: "Paramètres P1/P2 hors limites",
    0x6D00: "Instruction non supportée",
    0x6E00: "Classe non supportée",
    0x6F00: "Erreur sans diagnostic",
}


def sw_text(sw: int) -> str:
    if sw in SW_TEXT:
        return SW_TEXT[sw]
    if sw >> 4 == 0x63C:
        return f"Vérification échouée, {sw & 0xF} essai(s) restant(s)"
    if sw >> 8 == 0x61:
        return f"{sw & 0xFF} octet(s) disponible(s) (GET RESPONSE)"
    if sw >> 8 == 0x6C:
        return f"Longueur attendue : {sw & 0xFF}"
    return "Statut inconnu"


def parse_hex(s: str) -> bytes:
    clean = "".join(s.split()).replace("0x", "")
    if not clean or len(clean) % 2 or any(c not in "0123456789abcdefABCDEF" for c in clean):
        raise ChipError("Commande invalide : il faut des octets en hexadécimal (ex. 00 A4 00 00 02 3F 00).")
    return bytes.fromhex(clean)


def parse_tlv(data: bytes, depth: int = 0) -> list:
    """Décode du BER-TLV. S'arrête proprement sur du remplissage (00) ou des données qui ne sont pas du TLV."""
    out, i = [], 0
    while i < len(data) and data[i] not in (0x00, 0xFF):
        j = i
        tag = data[j]; j += 1
        if tag & 0x1F == 0x1F:                                  # tag sur plusieurs octets
            while j < len(data) and data[j] & 0x80:
                j += 1
            j += 1
        if j >= len(data):
            break
        ln = data[j]; j += 1
        if ln & 0x80:
            n = ln & 0x7F
            if n == 0 or n > 2 or j + n > len(data):
                break
            ln = int.from_bytes(data[j:j + n], "big"); j += n
        if j + ln > len(data):
            break
        val = data[j:j + ln]
        node = {"tag": _tag_hex(data, i), "hex": val.hex(" ").upper()}
        node["ascii"] = "".join(chr(c) if 32 <= c < 127 else "." for c in val)
        if tag & 0x20 and depth < 4:
            node["children"] = parse_tlv(val, depth + 1)
        out.append(node)
        i = j + ln
    return out


def _tag_hex(data: bytes, i: int) -> str:
    k = i + 1
    if data[i] & 0x1F == 0x1F:
        while k < len(data) and data[k] & 0x80:
            k += 1
        k += 1
    return data[i:k].hex().upper()


def decode_atr(atr: bytes) -> dict:
    info = {"hex": atr.hex(" ").upper(), "length": len(atr)}
    try:
        a = ATR(list(atr))
        hist = bytes(a.getHistoricalBytes())
        info["convention"] = {0x3B: "Directe (3B)", 0x3F: "Inverse (3F)"}.get(atr[0], "?")
        info["protocols"] = ", ".join(sorted(a.getSupportedProtocols())) or "—"
        info["historical"] = hist.hex(" ").upper()
        info["historical_ascii"] = "".join(chr(b) if 32 <= b < 127 else "." for b in hist)
    except Exception:
        info["convention"] = info["protocols"] = info["historical"] = info["historical_ascii"] = "—"
    return info


class Chip:
    """Une seule connexion persistante à la carte : l'état (fichier sélectionné, authentification)
    est conservé entre deux commandes, comme dans un vrai terminal."""

    def __init__(self):
        self.lock = threading.RLock()
        self.conn = None
        self.reader_name = None

    def _reader(self):
        """Choisit un lecteur : préfère un OMNIKEY s'il y en a un (meilleur support des cartes
        mémoire que l'ACR39U d'après nos tests), sinon le premier lecteur PC/SC branché."""
        found = pcsc_readers()
        if not found:
            return None
        return next((r for r in found if "OMNIKEY" in str(r).upper()), found[0])

    def _drop(self):
        if self.conn is not None:
            try:
                self.conn.disconnect()
            except Exception:
                pass
        self.conn = None

    def _connect(self, reader):
        """Essaie plusieurs protocoles de connexion : les lecteurs ne négocient pas tous
        les cartes à mémoire (synchrones) de la même façon. T=0/T=1 pour les cartes à
        microprocesseur, RAW en secours pour les cartes à mémoire sans protocole ISO."""
        last_exc = None
        for proto in (CardConnection.T0_protocol | CardConnection.T1_protocol,
                      CardConnection.T0_protocol,
                      CardConnection.T1_protocol,
                      CardConnection.RAW_protocol):
            c = reader.createConnection()
            try:
                c.connect(proto)
                self.conn = c
                return
            except NoCardException:
                raise
            except CardConnectionException as e:
                last_exc = e
        raise last_exc

    def status(self) -> dict:
        if not AVAILABLE:
            return {"available": False}
        with self.lock:
            try:
                reader = self._reader()
            except Exception as e:
                return {"available": True, "reader": None, "present": False, "error": str(e)}
            if reader is None:
                self._drop()
                return {"available": True, "reader": None, "present": False}
            self.reader_name = str(reader)
            if self.conn is not None:
                try:
                    self.conn.getATR()
                except Exception:
                    self._drop()
            if self.conn is None:
                try:
                    self._connect(reader)
                except NoCardException:
                    return {"available": True, "reader": self.reader_name, "present": False}
                except Exception as e:
                    return {"available": True, "reader": self.reader_name, "present": True, "error": f"Carte détectée mais illisible : {e}"}
            return {"available": True, "reader": self.reader_name, "present": True, "atr": decode_atr(bytes(self.conn.getATR()))}

    def _require(self):
        if not AVAILABLE:
            raise ChipError("Le module de lecture de puce n'est pas installé (pyscard).")
        s = self.status()
        if not s.get("reader"):
            raise ChipError("Lecteur de puce introuvable. Est-il branché ?")
        if not s.get("present") or self.conn is None:
            raise ChipError(s.get("error") or "Aucune carte dans le lecteur.")

    def transmit(self, apdu: bytes) -> dict:
        """Envoie une APDU ; suit automatiquement les statuts 61xx (GET RESPONSE) et 6Cxx (mauvais Le)."""
        with self.lock:
            self._require()
            if len(apdu) < 4:
                raise ChipError("Une APDU fait au moins 4 octets (CLA INS P1 P2).")
            try:
                data, sw1, sw2 = self.conn.transmit(list(apdu))
                steps = [(apdu, bytes(data), sw1, sw2)]
                if sw1 == 0x6C:                                   # Le incorrect : on renvoie avec la bonne longueur
                    retry = bytes(apdu[:4]) + bytes([sw2])
                    data, sw1, sw2 = self.conn.transmit(list(retry))
                    steps.append((retry, bytes(data), sw1, sw2))
                out = bytes(data)
                while sw1 == 0x61:                                # données en attente
                    get = bytes([0x00, 0xC0, 0x00, 0x00, sw2])
                    data, sw1, sw2 = self.conn.transmit(list(get))
                    steps.append((get, bytes(data), sw1, sw2))
                    out += bytes(data)
            except (CardConnectionException, NoCardException) as e:
                self._drop()
                raise ChipError(f"Communication impossible avec la carte : {e}")
            sw = (sw1 << 8) | sw2
            return {
                "tx": apdu.hex(" ").upper(), "data": out.hex(" ").upper(),
                "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in out),
                "sw": f"{sw:04X}", "sw_text": sw_text(sw), "ok": sw == 0x9000,
                "steps": [{"tx": t.hex(" ").upper(), "rx": d.hex(" ").upper(), "sw": f"{a:02X}{b:02X}"} for t, d, a, b in steps],
            }

    def reset(self) -> dict:
        """Réinitialisation à chaud : coupe puis rétablit l'alimentation de la carte."""
        with self.lock:
            self._drop()
            return self.status()

    def _raw(self, apdu: list) -> tuple:
        """Envoi direct, sans revérifier la carte à chaque fois (rapide). Gère 6Cxx (mauvais Le) et 61xx (suite)."""
        data, sw1, sw2 = self.conn.transmit(apdu)
        if sw1 == 0x6C:
            data, sw1, sw2 = self.conn.transmit(apdu[:4] + [sw2])
        out = bytes(data)
        while sw1 == 0x61:
            data, sw1, sw2 = self.conn.transmit([0x00, 0xC0, 0x00, 0x00, sw2])
            out += bytes(data)
        return out, (sw1 << 8) | sw2

    def explore(self) -> dict:
        """Parcourt la carte : liste des applications (EF.DIR), puis pour chacune lecture des fichiers par numéro court (SFI 1 à 30).
        Commandes ISO 7816 standard uniquement, sans aucune commande propre au paiement."""
        with self.lock:
            self._require()
            try:
                self._raw([0x00, 0xA4, 0x00, 0x0C, 0x02, 0x3F, 0x00])
                apps = []
                data, sw = self._raw([0x00, 0xB0, 0x9E, 0x00, 0x00])           # EF.DIR par SFI 30
                if sw != 0x9000:
                    self._raw([0x00, 0xA4, 0x02, 0x04, 0x02, 0x2F, 0x00])
                    data, sw = self._raw([0x00, 0xB0, 0x00, 0x00, 0x00])
                seen = set()
                for t in parse_tlv(data):
                    if t["tag"] != "61":
                        continue
                    kids = {k["tag"]: k for k in t.get("children", [])}
                    aid = kids.get("4F", {}).get("hex", "")
                    if not aid or aid in seen:
                        continue
                    seen.add(aid)
                    apps.append({"aid": aid, "label": bytes.fromhex(kids["50"]["hex"]).decode("latin-1") if "50" in kids else ""})
                if not apps:                                                    # pas d'EF.DIR : on lit au moins la racine
                    apps = [{"aid": "", "label": "Racine de la carte (3F00)"}]
                for app in apps:
                    if app["aid"]:
                        b = bytes.fromhex(app["aid"])
                        _, sw = self._raw([0x00, 0xA4, 0x04, 0x00, len(b)] + list(b))
                    else:
                        _, sw = self._raw([0x00, 0xA4, 0x00, 0x0C, 0x02, 0x3F, 0x00])
                    app["sw"], app["sw_text"], app["files"] = f"{sw:04X}", sw_text(sw), []
                    if sw != 0x9000:
                        continue
                    for sfi in range(1, 31):
                        data, sw = self._raw([0x00, 0xB0, 0x80 | sfi, 0x00, 0x00])
                        if sw in (0x6A82, 0x6A83, 0x6A86):                      # fichier absent
                            continue
                        f = {"sfi": sfi, "sw": f"{sw:04X}", "sw_text": sw_text(sw), "size": len(data)}
                        if sw == 0x9000:
                            f["hex"] = data.hex(" ").upper()
                            f["ascii"] = "".join(chr(c) if 32 <= c < 127 else "." for c in data)
                            f["tlv"] = parse_tlv(data)
                            f["empty"] = not any(data)
                        app["files"].append(f)
            except (CardConnectionException, NoCardException) as e:
                self._drop()
                raise ChipError(f"Communication impossible avec la carte : {e}")
            return {"apps": apps}

    def dump(self, start: int, length: int) -> dict:
        """Lecture mémoire d'une carte à mémoire (SLE4442, SLE4428...) via la commande standard READ BINARY de PC/SC."""
        if not (0 <= start < 65536) or not (1 <= length <= 1024):
            raise ChipError("Plage invalide (longueur 1 à 1024 octets).")
        with self.lock:
            self._require()
            buf, err = b"", None
            for off in range(start, start + length, 32):
                n = min(32, start + length - off)
                try:
                    data, sw1, sw2 = self.conn.transmit([0xFF, 0xB0, off >> 8, off & 0xFF, n])
                except (CardConnectionException, NoCardException) as e:
                    self._drop()
                    err = str(e)
                    break
                if (sw1, sw2) != (0x90, 0x00):
                    err = f"{sw1:02X}{sw2:02X} : {sw_text((sw1 << 8) | sw2)}"
                    break
                buf += bytes(data)
            return {"start": start, "hex": buf.hex(" ").upper(), "length": len(buf), "error": err}

    def write_memory(self, start: int, data: bytes, psc: bytes | None = None) -> dict:
        """Écriture sur une carte à mémoire (SLE4428, SLE4442...) via UPDATE BINARY (FF D6), par blocs de 32 octets.
        La plupart de ces cartes refusent toute écriture tant qu'on n'a pas présenté leur code d'accès (PSC) :
        2 octets pour une SLE4428, 3 pour une SLE4442. Code d'usine le plus courant : tout à FF.
        Repéré avec l'aide de l'utilisateur ce soir — merci à lui : FF D0 (la convention « carte mémoire »
        générique de PC/SC) n'est pas implémentée par le pilote de ce Mac, mais FF D6 (UPDATE BINARY ISO
        standard) l'est, une fois la carte déverrouillée."""
        if not (0 <= start < 65536) or not (1 <= len(data) <= 1024):
            raise ChipError("Plage invalide (1 à 1024 octets).")
        with self.lock:
            self._require()
            if psc:
                self.presented_pin(psc)
            written = 0
            for off in range(0, len(data), 32):
                block = data[off:off + 32]
                addr = start + off
                try:
                    _, sw1, sw2 = self.conn.transmit([0xFF, 0xD6, addr >> 8, addr & 0xFF, len(block)] + list(block))
                except (CardConnectionException, NoCardException) as e:
                    self._drop()
                    raise ChipError(f"Communication impossible avec la carte : {e}")
                if (sw1, sw2) != (0x90, 0x00):
                    sw = (sw1 << 8) | sw2
                    raise ChipError(f"Écriture interrompue à l'octet {written} ({sw:04X} : {sw_text(sw)}).")
                written += len(block)
            return {"start": start, "written": written}

    def presented_pin(self, pin: bytes) -> dict:
        """Présente le code d'accès (PSC) à la carte avant une écriture protégée (VERIFY, FF 20 00 00).
        2 octets pour une SLE4428, 3 pour une SLE4442 ; FF FF (ou FF FF FF) est le code d'usine le plus courant."""
        with self.lock:
            self._require()
            try:
                _, sw1, sw2 = self.conn.transmit([0xFF, 0x20, 0x00, 0x00, len(pin)] + list(pin))
            except (CardConnectionException, NoCardException) as e:
                self._drop()
                raise ChipError(f"Communication impossible avec la carte : {e}")
            sw = (sw1 << 8) | sw2
            if sw != 0x9000:
                raise ChipError(f"Code refusé ({sw:04X} : {sw_text(sw)}).")
            return {"msg": "Code accepté."}

    def update_binary(self, sfi: int, offset: int, data: bytes) -> dict:
        """Écriture ISO 7816-4 standard (UPDATE BINARY, 00 D6) dans un fichier déjà sélectionné par numéro court.
        Marche sur une carte à microprocesseur si le fichier visé autorise l'écriture sans condition
        (sinon la carte renvoie 6982/6985 : condition de sécurité non remplie — code non présenté, ou écriture non permise)."""
        if not (1 <= sfi <= 30):
            raise ChipError("Le numéro de fichier (SFI) va de 1 à 30.")
        if not (0 <= offset < 256) or not (1 <= len(data) <= 255):
            raise ChipError("Décalage ou longueur invalide (max 255 octets par écriture).")
        with self.lock:
            self._require()
            try:
                _, sw1, sw2 = self.conn.transmit([0x00, 0xD6, 0x80 | sfi, offset, len(data)] + list(data))
            except (CardConnectionException, NoCardException) as e:
                self._drop()
                raise ChipError(f"Communication impossible avec la carte : {e}")
            sw = (sw1 << 8) | sw2
            if sw != 0x9000:
                raise ChipError(f"Écriture refusée par la carte ({sw:04X} : {sw_text(sw)}).")
            return {"msg": "Écriture réussie."}


chip = Chip()
