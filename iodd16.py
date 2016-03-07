# -*- coding: utf-8 -*-
"""
Copyright (C) 2016 Riccardo Magliocchetti <riccardo.magliocchetti@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from lxml.html import fromstring
from lxml.etree import fromstring as xmlfromstring
import requests

from cStringIO import StringIO
from collections import defaultdict, Counter
from urlparse import urlparse, parse_qs

import errno
import sys
import csv
import re
import os


DEBUG = False

FSCKED = {}

COMUNI_CSV_PATH = os.path.join('data', 'comuni.csv')


"""
dati interessati 2013 - 2015
"""

class GazzettaScraper(object):
    """
    gazzetta amministrativa
    #resourceList .resourceContainerTitle a
    i link hanno attributo type application/octet-stream
    ALBO DEI BENEFICIARI in resourceContainerTitle
    """
    path = '#resourceList .resourceContainerTitle a'

class TrasparenzaScuole(object):
    uuid_bandi_gara = '6F952777-35F7-495E-87BC-2F006FFAD730'
    base_url = 'https://www.trasparenzascuole.it/Public/AmministrazioneTrasparente.aspx?P={}'.format(uuid_bandi_gara)
    codice_fiscale_re = re.compile('Codice fiscale: (\d+) ')
    """
    https://www.trasparenzascuole.it/Public/AmministrazioneTrasparente.aspx?Customer_ID=8b259f2b-e52b-42e4-821b-240d15bb0dcf&P=6F952777-35F7-495E-87BC-2F006FFAD730
    """
    def get_anac_url(self, customer_id):
        return '{}&Customer_ID={}'.format(self.base_url, customer_id)

    def anac(self, customer_ids):
        data = []
        for customer in customer_ids:
            url = self.get_anac_url(customer)
            r = requests.get(url, verify=False)
            h = fromstring(r.text)
            anchors = h.cssselect('.Table_link_trasparenza .text_link a')
            if not anchors:
                data.append((False, piva, None))
                continue
            anagrafica = h.cssselect('.anagrafica_col')[0].text_content()
            piva = self.codice_fiscale_re.search(anagrafica).groups(0)[0]
            for anchor in anchors:
                href = anchor.get('href')
                data.append((True, piva, href))
        return data


class StudioK(object):
    """http://albo.studiok.it/casella/trasparenza/?type=xml"""
    """ALLEGATI: scrape http://albo.studiok.it/lozza/contratti/dettaglio.php?id=MEST0000000052015"""

    COMUNE_RE = re.compile('ART.26  (.+)$')

    def get_concessioni_url(self, comune):
        return "http://albo.studiok.it/{}/trasparenza/?type=excel".format(comune)

    def get_trasparenza_url(self, comune):
        return "http://albo.studiok.it/{}/trasparenza/".format(comune)

    def concessioni(self, comuni, header):
        data = []

        piva_comuni = {}
        with open(COMUNI_CSV_PATH, 'r') as f:
            reader = csv.reader(f, delimiter=',')
            for comune, piva in reader:
                piva_comuni[comune.strip().lower()] = piva

        for comune in comuni:
            url = self.get_trasparenza_url(comune)
            r = requests.get(url)

            html = fromstring(r.text)
            try:
                h1 = html.cssselect('h1')[0].text_content()
            except IndexError:
                print "non trovo h1 per comune {}, skippo".format(comune)
                continue
            try:
                comune_norm = self.COMUNE_RE.search(h1).groups(0)[0].strip().lower()
            except AttributeError:
                print "per comune {} h1 fatto in modo strano, skippo: {}".format(comune, h1)
                continue

            try:
                piva = piva_comuni[comune_norm]
            except KeyError:
                print "non trovo comune {} normalizzato {}".format(comune, comune_norm)
                continue

            comune_data = []

            url = self.get_concessioni_url(comune)
            r = requests.get(url)

            # in python2 csv does not handle unicode objects
            response_text = r.text.encode(encoding='utf-8', errors='replace')
            f = StringIO(response_text)
            for row in csv.DictReader(f, fieldnames=header, delimiter='\t'):
                row['Url'] = url
                try:
                    del row[None]
                except:
                    pass
                comune_data.append(row)

            data.append((piva, url, comune_data))
        return data

def collect_platforms():
    collected = defaultdict(list)
    with open(sys.argv[1], 'r') as f:
        reader = csv.reader(f, delimiter='\t')
        for row in reader:
            pa = row[0]
            url = row[1]

            o = urlparse(url)

            if not o.netloc:
                FSCKED[pa] = url
                continue

            collected[o.netloc].append((pa, o))

    return collected

def trasparenza_scuole_anac(data):
    parsed_qs = [parse_qs(url.query) for _, url in data]
    cids = [qs['Customer_ID'][0] for qs in parsed_qs]
    scraper = TrasparenzaScuole()
    scraped_data = scraper.anac(cids)
    anac = [(piva, anchor) for found, piva, anchor in scraped_data if found]
    not_anac = [(piva,) for found, piva, _ in scraped_data if not found]
    with open('ANAC.csv', 'w+') as outfile:
        writer = csv.writer(outfile, delimiter=',')
        writer.writerows(anac)

    with open('NO-ANAC.csv', 'w+') as outfile:
        writer = csv.writer(outfile, delimiter=',')
        writer.writerows(not_anac)


def studiok_atti_di_concessione(data):
    """
    atti/piva.csv
    link sorgente, imprese, importo, norma, ufficio, modalità, allegati
    """
    trasparenza_re = re.compile('/trasparenza/(\w+)/')
    comuni_re = re.compile('/comuni/(\w+)/')

    comuni = []
    for pa, url in data:
        match = trasparenza_re.match(url.path)
        if not match:
            match = comuni_re.match(url.path)
        comune = match.groups(0)[0]
        comuni.append(comune)

    header = (
        'Registro', 'Indirizzo Beneficiario', 'Modalità', 'Località beneficiario', 'Beneficiario',
        'Data Annullamento', 'Norma', 'Oggetto', 'Codice Fiscale', 'Descrizione', 'Partita IVA',
        'Tipo Pubblicazione', 'Data Registro', 'Ufficio Funzione', 'Numero Pubblicazione',
        'Estratto', 'Importo', 'Annullamento'
    )
    scraper = StudioK()
    scraped_data = scraper.concessioni(comuni, header)

    mkdir('atti')

    for piva, url, comune_data in scraped_data:
        filename = os.path.join('atti', '{}.csv'.format(piva))
        with open(filename, 'w+') as outfile:
            output_header = ('Url',)+header
            writer = csv.DictWriter(outfile, fieldnames=output_header, delimiter=',')
            writer.writerows(comune_data)


def mkdir(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise

if __name__ == '__main__':
    data = collect_platforms()
    #trasparenza_scuole_anac(data['www.trasparenzascuole.it'])
    studiok_atti_di_concessione(data['www.studiok.it'])

    counter = Counter()
    for k, v in data.items():
       counter[k] = len(v)

    common = counter.most_common(5)

    if DEBUG:
        for domain, _ in common:
            print("DOMINIO", domain)
            for urls in data[domain]:
                print(urls[1].geturl())
