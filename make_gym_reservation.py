from locale import setlocale, LC_TIME
from sys import exit
from queue import Queue
from tabulate import tabulate
from os import path, listdir
from threading import Thread
from webdriver_manager.firefox import GeckoDriverManager
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime, timedelta
from argparse import ArgumentParser
from json import load
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.action_chains import ActionChains
from time import sleep
from pathlib import Path
from selenium import webdriver
import logging
from pdb import set_trace
time  # !/usr/bin/venv python3

CHROMEDRIVER = ""
GECKODRIVER = ""
MAIN_PAGE = "https://www.onlinejoining.com/apps/Castillo/empezar.php"
BASE_DIR = path.dirname(path.abspath(__file__))
ALLOWED_ACTIONS = ["make_reservations", "generate_reservations_report"]

# Change timelocale to current account's language. In this case, spanish
setlocale(LC_TIME, 'es_ES')


def setup_logging(file):
    logger = logging.getLogger(file)

    logger.setLevel(logging.DEBUG)

    # Create logging formatter
    logFormatter = logging.Formatter(
        fmt=f'%(asctime)s - {file} - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # Not needed since:
    # - We are running from a Cron job
    # - Multiple threads are running so it would be messy
    # - The logging is being saved into a file anyway

    # Create console handler
    consoleHandler = logging.StreamHandler()
    consoleHandler.setLevel(logging.DEBUG)
    consoleHandler.setFormatter(logFormatter)

    # Add console handler to logger
    logger.addHandler(consoleHandler)

    # Create file handler
    fileHandler = logging.FileHandler(
        f'{BASE_DIR}/logs/{datetime.now().strftime("%Y_%m_%d")}_{file}_.log')
    fileHandler.setLevel(logging.DEBUG)
    fileHandler.setFormatter(logFormatter)

    # Add file handler to logger
    logger.addHandler(fileHandler)

    return logger


def print_reservations_report(report):
    report_header = ["Nombre", "Fecha", "Hora", "Área", "Estado"]
    report_data = []
    for name in report:
        dates = []
        times = []
        areas = []
        states = []
        for date in report[name]:
            dates.append(date)
            times.append(report[name][date]["time"])
            areas.append(report[name][date]["area"])
            states.append(report[name][date]["status"])
        report_data.append([name, '\n'.join(dates), '\n'.join(
            times), '\n'.join(areas), '\n'.join(states)])

    print("")
    print(tabulate(report_data, report_header, tablefmt="fancy_grid"))


def make_reservation(file, queue):
    file_name = file.split('/')[-1].replace(".json", "")
    logger = setup_logging(f"{file_name}_make_reservation")
    report_data = {file_name: {}}
    logger.info(f"Processing file {file}")
    driver = None
    try:
        driver = webdriver.Chrome(CHROMEDRIVER)
        # driver = webdriver.Firefox(GECKODRIVER)

        with open(file) as infile:
            data = load(infile)

        # Access the reservation web page
        driver.get(MAIN_PAGE)

        if 'f_btn' in driver.page_source:
            try:
                driver.find_element_by_class_name("f_btn").click()
            except:
                pass

        # Login
        driver.find_element_by_id("user").send_keys(data["user"])
        sleep(2)
        driver.find_element_by_id("pass").send_keys(data["pass"])
        sleep(2)
        driver.find_element_by_class_name("login100-form-btn").click()
        sleep(2)

        # Move to the reservations section
        driver.find_element_by_class_name("container2").click()
        sleep(2)
        driver.find_element_by_xpath('//*[@id="mySidenav"]/a[4]').click()
        sleep(2)

        # Make reservation for each day
        for day, day_info in data["days"].items():
            area = day_info["area"]
            time = day_info["time"]

            report_data[file_name][day] = {"area": area, "time": time, "status": "No reservado"}

            logger.info(f"Attempting to book '{area}' for {day}@{time}")

            # Select a day in the calendar
            element = driver.find_element_by_xpath(f"//*[@data-date='{day}']")
            actions = ActionChains(driver)
            actions.move_to_element(element).click(element).perform()
            # sleep(10)

            # Select the corresponding campus
            # Check if the information have loaded by brute force
            while(True):
                try:
                    Select(driver.find_element_by_id("sedes")).select_by_visible_text(
                        'EL CASTILLO COUNTRY CLUB')
                    break
                except:
                    pass

            # Selected the desired area
            # Check if the information have loaded by brute force
            while(True):
                try:
                    Select(driver.find_element_by_id("areas")).select_by_visible_text(area)
                    break
                except:
                    pass

            # Confirm
            driver.find_element_by_xpath("//*[contains(text(), 'Buscar')]").click()
            sleep(2)

            # Make reservation
            for panel in driver.find_elements_by_class_name("panel"):
                # Look for the panel that has the time we are looking for
                elements = panel.find_elements_by_class_name("titHorarios")
                if elements[10].text == time:
                    # Make a reservation or put us in the waiting list
                    spaces_left = int(elements[1].text)
                    elements[2].click()
                    # There are two (possibly more) accept buttons but only one shown
                    sleep(2)
                    for button in driver.find_elements_by_class_name("btn-success"):
                        sleep(2)
                        if button.is_displayed() and button.is_enabled():
                            button.click()
                            sleep(2)
                            if spaces_left > 0:
                                report_data[file_name][day]["status"] = "Reservado"
                                logger.info(
                                    f"You have booked '{area}' for {day}@{time}")
                            else:
                                report_data[file_name][day]["status"] = "Lista de espera"
                                logger.info(
                                    f"You were put in the waiting list of '{area}' for {day}@{time}")
                            break
                    else:
                        continue
                    break
            else:
                logger.warning(
                    f"Ups, {time} is not a valid time for '{area}'")

            # Go back
            driver.find_element_by_class_name("iconos").click()
            sleep(2)

    except Exception as e:
        logger.exception("Something unexpected occured")
    finally:
        if driver:
            driver.close()

    queue.put(report_data)


def make_reservations(files):
    queue = Queue()
    threads = []
    for file in files:
        t = Thread(target=make_reservation, args=(file, queue,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    report_data = {}
    while queue.qsize() > 0:
        report_data.update(queue.get())

    print_reservations_report(report_data)


def gather_report_data(file, queue):
    file_name = file.split('/')[-1].replace(".json", "")
    logger = setup_logging(f"{file_name}_report_generation")
    report_data = {file_name: {}}
    logger.info(f"Processing file {file}")
    driver = None
    try:
        driver = webdriver.Chrome(CHROMEDRIVER)
        # driver = webdriver.Firefox(GECKODRIVER)

        with open(file) as infile:
            data = load(infile)

        # Access the reservation web page
        driver.get(MAIN_PAGE)

        # Login
        driver.find_element_by_id("user").send_keys(data["user"])
        sleep(2)
        driver.find_element_by_id("pass").send_keys(data["pass"])
        sleep(2)
        driver.find_element_by_class_name("login100-form-btn").click()
        sleep(2)

        # Move to the reservations section
        driver.find_element_by_class_name("container2").click()
        sleep(2)
        driver.find_element_by_xpath('//*[@id="mySidenav"]/a[4]').click()
        sleep(2)

        # Access the reservations list
        driver.find_element_by_xpath("//*[contains(text(), 'Visitas reservadas')]").click()
        sleep(2)

        # Check the reservations list
        for day, day_info in data["days"].items():
            area = day_info["area"]
            time = day_info["time"]
            report_data[file_name][day] = {"area": area, "time": time, "status": "No reservado"}

            for panel in driver.find_elements_by_class_name("panel"):
                try:
                    # Look for the panel that has the time we are looking for
                    labels = panel.find_elements_by_css_selector('label')

                    panel_date = labels[2].text.split(',')[-1]  # Original: Monday,10 nov.2021
                    # panel_time = labels[4].text.split(' - ')[0]  # Original: 07:00 - 08:45
                    if datetime.strptime(panel_date, "%d %b.%Y") == datetime.strptime(day, "%Y-%m-%d"):
                        report_data[file_name][day]["status"] = "Reservado"
                        break
                except:
                    # Maybe was not in the correct format?
                    # TODO: add better logging
                    pass

        # Go back
        driver.find_element_by_class_name("iconos").click()
        sleep(2)

        # Access the waiting list
        driver.find_element_by_xpath("//*[contains(text(), 'Lista de espera')]").click()
        sleep(2)

        # Check the waiting list
        for day, day_info in data["days"].items():
            area = day_info["area"]
            time = day_info["time"]
            for panel in driver.find_elements_by_class_name("panel"):
                try:
                    # Look for the panel that has the time we are looking for
                    labels = panel.find_elements_by_css_selector('label')

                    panel_date = labels[2].text.split(',')[-1]  # Original: Monday,10 nov.2021
                    # panel_time = labels[4].text.split(' - ')[0]  # Original: 07:00 - 08:45

                    if datetime.strptime(panel_date, "%d %b.%Y") == datetime.strptime(day, "%Y-%m-%d"):
                        report_data[file_name][day]["status"] = "Lista de Espera"
                        break
                except Exception as e:
                    # Maybe was not in the correct format?
                    # TODO: add better logging
                    pass

    except Exception as e:
        logger.exception("Something unexpected occured")
    finally:
        if driver:
            driver.close()

    queue.put(report_data)


def generate_reservations_report(files):
    queue = Queue()
    threads = []
    for file in files:
        t = Thread(target=gather_report_data, args=(file, queue,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    report_data = {}
    while queue.qsize() > 0:
        report_data.update(queue.get())

    print_reservations_report(report_data)


def main():
    global CHROMEDRIVER

    parser = ArgumentParser(
        description="This script helps making gym reservations automatically based on a JSON file with the required info on the day, area and time that the reservation is needed")
    parser.add_argument('--files', metavar="file1.json,file2.json,...",
                        help='Comma separated list of specific json files')
    parser.add_argument('--action', choices=ALLOWED_ACTIONS,
                        default="make_reservations", help='Actions the script can perform')
    args = parser.parse_args()

    files_string = args.files
    action = args.action

    if files_string:
        file_names = files_string.split(',')
    else:
        # Get all json files
        file_names = listdir(f"{BASE_DIR}/json_files")

    files = []
    for file_name in file_names:
        file = f"{BASE_DIR}/json_files/{file_name}"
        # Only process files which have been modified in the past week
        if datetime.fromtimestamp(path.getmtime(file)) > datetime.now() - timedelta(days=7):
            files.append(file)

    if action in ALLOWED_ACTIONS:
        CHROMEDRIVER = ChromeDriverManager().install()
        # GECKODRIVER = GeckoDriverManager().install()
        eval(action)(files)
    else:
        exit(f"Unrecognized action '{action}'!")


if __name__ == "__main__":
    main()
